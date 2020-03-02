# -*- coding: utf-8 -*-

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from keystoneauth1 import exceptions as ksa_exceptions
from keystoneauth1 import loading
from openstack import connection
from oslo_config import cfg
from oslo_log import log

from oslo_limit import exception
from oslo_limit import opts

CONF = cfg.CONF
LOG = log.getLogger(__name__)
_SDK_CONNECTION = None
opts.register_opts(CONF)


def _get_keystone_connection():
    global _SDK_CONNECTION
    if not _SDK_CONNECTION:
        try:
            auth = loading.load_auth_from_conf_options(
                CONF, group='oslo_limit')
            session = loading.load_session_from_conf_options(
                CONF, group='oslo_limit', auth=auth)
            _SDK_CONNECTION = connection.Connection(session=session).identity
        except (ksa_exceptions.NoMatchingPlugin,
                ksa_exceptions.MissingRequiredOptions,
                ksa_exceptions.MissingAuthPlugin,
                ksa_exceptions.DiscoveryFailure,
                ksa_exceptions.Unauthorized) as e:
            msg = 'Unable to initialize OpenStackSDK session: %s' % e
            LOG.error(msg)
            raise exception.SessionInitError(e)

    return _SDK_CONNECTION


class Enforcer(object):

    def __init__(self, usage_callback):
        """An object for checking usage against resource limits and requests.

        :param usage_callback: A callable function that accepts a project_id
                               string as a parameter and calculates the current
                               usage of a resource.
        :type usage_callback: callable function
        """
        if not callable(usage_callback):
            msg = 'usage_callback must be a callable function.'
            raise ValueError(msg)

        self.connection = _get_keystone_connection()
        self.model = self._get_model_impl(usage_callback)

    def _get_enforcement_model(self):
        """Query keystone for the configured enforcement model."""
        return self.connection.get('/limits/model').json()['model']['name']

    def _get_model_impl(self, usage_callback):
        """get the enforcement model based on configured model in keystone."""
        model = self._get_enforcement_model()
        for impl in _MODELS:
            if model == impl.name:
                return impl(usage_callback)
        raise ValueError("enforcement model %s is not supported" % model)

    def enforce(self, project_id, deltas):
        """Check resource usage against limits for resources in deltas

        From the deltas we extract the list of resource types that need to
        have limits enforced on them.

        From keystone we fetch limits relating to this project_id and the
        endpoint specified in the configuration.

        Using the usage_callback specified when creating the enforcer,
        we fetch the existing usage.

        We then add the existing usage to the provided deltas to get
        the total proposed usage. This total proposed usage is then
        compared against all appropriate limits that apply.

        Note if there are no registered limits for a given resource type,
        we fail the enforce in the same way as if we defaulted to
        a limit of zero, i.e. do not allow any use of a resource type
        that does not have a registered limit.

        :param project_id: The project to check usage and enforce limits
                           against.
        :type project_id: string
        :param deltas: An dictionary containing resource names as keys and
                       requests resource quantities as positive integers.
                       We only check limits for resources in deltas.
                       Specify a quantity of zero to check current usage.
        :type deltas: dictionary

        :raises exception.ClaimExceedsLimit: when over limits
        """
        if not project_id or not isinstance(project_id, str):
            msg = 'project_id must be a non-empty string.'
            raise ValueError(msg)
        if not isinstance(deltas, dict) or len(deltas) == 0:
            msg = 'deltas must be a non-empty dictionary.'
            raise ValueError(msg)

        for k, v in deltas.items():
            if not isinstance(k, str):
                raise ValueError('resource name is not a string.')
            elif not isinstance(v, int):
                raise ValueError('resource limit is not an integer.')

        self.model.enforce(project_id, deltas)


class _FlatEnforcer(object):

    name = 'flat'

    def __init__(self, usage_callback):
        self._usage_callback = usage_callback
        self._utils = _EnforcerUtils()

    def enforce(self, project_id, deltas):
        resources_to_check = list(deltas.keys())
        # Always check the limits in the same order, for predictable errors
        resources_to_check.sort()

        project_limits = self._utils.get_project_limits(project_id,
                                                        resources_to_check)
        current_usage = self._usage_callback(project_id, resources_to_check)

        self._utils.enforce_limits(project_id, project_limits,
                                   current_usage, deltas)


class _StrictTwoLevelEnforcer(object):

    name = 'strict-two-level'

    def __init__(self, usage_callback):
        self._usage_callback = usage_callback

    def enforce(self, project_id, deltas):
        raise NotImplementedError()


_MODELS = [_FlatEnforcer, _StrictTwoLevelEnforcer]


class _LimitNotFound(Exception):
    def __init__(self, resource):
        msg = "Can't find the limit for resource %(resource)s" % {
            'resource': resource}
        self.resource = resource
        super(_LimitNotFound, self).__init__(msg)


class _EnforcerUtils(object):
    """Logic common used by multiple enforcers"""

    def __init__(self):
        self.connection = _get_keystone_connection()

        # get and cache endpoint info
        endpoint_id = CONF.oslo_limit.endpoint_id
        self._endpoint = self.connection.get_endpoint(endpoint_id)
        if not self._endpoint:
            raise ValueError("can't find endpoint for %s" % endpoint_id)
        self._service_id = self._endpoint.service_id
        self._region_id = self._endpoint.region_id

    @staticmethod
    def enforce_limits(project_id, limits, current_usage, deltas):
        """Check that proposed usage is not over given limits

        :param project_id: project being checked
        :param limits: list of (resource_name,limit) pairs
        :param current_usage: dict of resource name and current usage
        :param deltas: dict of resource name and proposed additional usage

        :raises exception.ClaimExceedsLimit: raise if over limit
        """
        over_limit_list = []
        for resource_name, limit in limits:
            if resource_name not in current_usage:
                msg = "unable to get current usage for %s" % resource_name
                raise ValueError(msg)

            current = int(current_usage[resource_name])
            delta = int(deltas[resource_name])
            proposed_usage_total = current + delta
            if proposed_usage_total > limit:
                over_limit_list.append(exception.OverLimitInfo(
                    resource_name, limit, current, delta))

        if len(over_limit_list) > 0:
            LOG.debug("hit limit for project: %s", over_limit_list)
            raise exception.ProjectOverLimit(project_id, over_limit_list)

    def get_project_limits(self, project_id, resource_names):
        """Get all the limits for given project a resource_name list

        We will raise ClaimExceedsLimit if no limit is found to ensure that
        all clients of this library react to this situation in the same way.

        :param project_id:
        :param resource_names: list of resource_name strings
        :return: list of (resource_name,limit) pairs

        :raises exception.ClaimExceedsLimit: if no limit is found
        """
        # Using a list to preserver the resource_name order
        project_limits = []
        missing_limits = []
        for resource_name in resource_names:
            try:
                limit = self._get_limit(project_id, resource_name)
                project_limits.append((resource_name, limit))
            except _LimitNotFound:
                missing_limits.append(resource_name)

        if len(missing_limits) > 0:
            over_limit_list = [exception.OverLimitInfo(name, 0, 0, 0)
                               for name in missing_limits]
            raise exception.ProjectOverLimit(project_id, over_limit_list)

        return project_limits

    def _get_limit(self, project_id, resource_name):
        # TODO(johngarbutt): might need to cache here
        project_limit = self._get_project_limit(project_id, resource_name)
        if project_limit:
            return project_limit.resource_limit

        registered_limit = self._get_registered_limit(resource_name)
        if registered_limit:
            return registered_limit.default_limit

        LOG.error(
            "Unable to find registered limit for resource "
            "%(resource)s for %(service)s in region %(region)s.",
            {"resource": resource_name, "service": self._service_id,
             "region": self._region_id}, exec_info=False)
        raise _LimitNotFound(resource_name)

    def _get_project_limit(self, project_id, resource_name):
        limit = self.connection.limits(
            service_id=self._service_id,
            region_id=self._region_id,
            resource_name=resource_name,
            project_id=project_id)
        try:
            return next(limit)
        except StopIteration:
            return None

    def _get_registered_limit(self, resource_name):
        reg_limit = self.connection.registered_limits(
            service_id=self._service_id,
            region_id=self._region_id,
            resource_name=resource_name)
        try:
            return next(reg_limit)
        except StopIteration:
            return None
