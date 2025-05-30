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

from collections import defaultdict
from collections import namedtuple

from keystoneauth1 import exceptions as ksa_exceptions
from keystoneauth1 import loading
from openstack import connection
from openstack import exceptions as os_exceptions
from oslo_config import cfg
from oslo_log import log

from oslo_limit import exception
from oslo_limit import opts

CONF = cfg.CONF
LOG = log.getLogger(__name__)
_SDK_CONNECTION = None
opts.register_opts(CONF)


ProjectUsage = namedtuple('ProjectUsage', ['limit', 'usage'])


def _get_keystone_connection():
    global _SDK_CONNECTION
    if not _SDK_CONNECTION:
        try:
            auth = loading.load_auth_from_conf_options(
                CONF, group='oslo_limit')
            session = loading.load_session_from_conf_options(
                CONF, group='oslo_limit', auth=auth)
            ksa_opts = loading.get_adapter_conf_options(
                include_deprecated=False)
            conn_kwargs = {}
            for opt in ksa_opts:
                if opt.dest != 'valid_interfaces':
                    conn_kwargs['identity_' + opt.dest] = getattr(
                        CONF.oslo_limit, opt.dest)
            conn_kwargs['identity_interface'] = \
                CONF.oslo_limit.valid_interfaces
            _SDK_CONNECTION = connection.Connection(
                session=session,
                **conn_kwargs
            ).identity
        except (ksa_exceptions.NoMatchingPlugin,
                ksa_exceptions.MissingRequiredOptions,
                ksa_exceptions.MissingAuthPlugin,
                ksa_exceptions.DiscoveryFailure,
                ksa_exceptions.Unauthorized) as e:
            msg = 'Unable to initialize OpenStackSDK session: %s' % e
            LOG.error(msg)
            raise exception.SessionInitError(e)

    return _SDK_CONNECTION


class Enforcer:

    def __init__(self, usage_callback, cache=True):
        """An object for checking usage against resource limits and requests.

        :param usage_callback: A callable function that accepts a project_id
                               string as a parameter and calculates the current
                               usage of a resource.
        :type usage_callback: callable function
        :param cache: Whether to cache resource limits for the lifetime of this
                      enforcer. Defaults to True.
        :type cache: boolean
        """
        if not callable(usage_callback):
            msg = 'usage_callback must be a callable function.'
            raise ValueError(msg)

        self.connection = _get_keystone_connection()
        self.model = self._get_model_impl(usage_callback, cache=cache)

    def _get_enforcement_model(self):
        """Query keystone for the configured enforcement model."""
        return self.connection.get('/limits/model').json()['model']['name']

    def _get_model_impl(self, usage_callback, cache=True):
        """get the enforcement model based on configured model in keystone."""
        model = self._get_enforcement_model()
        for impl in _MODELS:
            if model == impl.name:
                return impl(usage_callback, cache=cache)
        raise ValueError("enforcement model %s is not supported" % model)

    def enforce(self, project_id, deltas):
        """Check resource usage against limits for resources in deltas

        From the deltas we extract the list of resource types that need to
        have limits enforced on them.

        From keystone we fetch limits relating to this project_id (if
        not None) and the endpoint specified in the configuration.

        Using the usage_callback specified when creating the enforcer,
        we fetch the existing usage.

        We then add the existing usage to the provided deltas to get
        the total proposed usage. This total proposed usage is then
        compared against all appropriate limits that apply.

        Note if there are no registered limits for a given resource type,
        we fail the enforce in the same way as if we defaulted to
        a limit of zero, i.e. do not allow any use of a resource type
        that does not have a registered limit.

        Note that if a project_id of None is provided, we just compare
        against the registered limits (i.e. use this for
        non-project-scoped limits)

        :param project_id: The project to check usage and enforce limits
                           against (or None).
        :type project_id: string
        :param deltas: An dictionary containing resource names as keys and
                       requests resource quantities as positive integers.
                       We only check limits for resources in deltas.
                       Specify a quantity of zero to check current usage.
        :type deltas: dictionary

        :raises exception.ClaimExceedsLimit: when over limits

        """
        if project_id is not None and (
                not project_id or not isinstance(project_id, str)):
            msg = 'project_id must be a non-empty string or None.'
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

    def calculate_usage(self, project_id, resources_to_check):
        """Calculate resource usage and limits for resources_to_check.

        From the list of resources_to_check, we collect the project's
        limit and current usage for each, exactly like we would for
        enforce(). This is useful for reporting current project usage
        and limits in a situation where enforcement is not desired.

        This should *not* be used to conduct custom enforcement, but
        rather only for reporting.

        :param project_id: The project for which to check usage and limits,
                           or None.
        :type project_id: string
        :param resources_to_check: A list of resource names to query.
        :type resources_to_check: list
        :returns: A dictionary of name:limit.ProjectUsage for the
                  requested names against the provided project.
        """
        if project_id is not None and (
                not project_id or not isinstance(project_id, str)):
            msg = 'project_id must be a non-empty string or None.'
            raise ValueError(msg)

        msg = ('resources_to_check must be non-empty sequence of '
               'resource name strings')
        try:
            if len(resources_to_check) == 0:
                raise ValueError(msg)
        except TypeError:
            raise ValueError(msg)

        for resource_name in resources_to_check:
            if not isinstance(resource_name, str):
                raise ValueError(msg)

        limits = self.model.get_project_limits(project_id, resources_to_check)
        usage = self.model.get_project_usage(project_id, resources_to_check)

        return {resource: ProjectUsage(limit, usage[resource])
                for resource, limit in limits}

    def get_registered_limits(self, resources_to_check):
        return self.model.get_registered_limits(resources_to_check)

    def get_project_limits(self, project_id, resources_to_check):
        return self.model.get_project_limits(project_id,
                                             resources_to_check)


class _FlatEnforcer:

    name = 'flat'

    def __init__(self, usage_callback, cache=True):
        self._usage_callback = usage_callback
        self._utils = _EnforcerUtils(cache=cache)

    def get_registered_limits(self, resources_to_check):
        return self._utils.get_registered_limits(resources_to_check)

    def get_project_limits(self, project_id, resources_to_check):
        return self._utils.get_project_limits(project_id, resources_to_check)

    def get_project_usage(self, project_id, resources_to_check):
        return self._usage_callback(project_id, resources_to_check)

    def enforce(self, project_id, deltas):
        resources_to_check = list(deltas.keys())
        # Always check the limits in the same order, for predictable errors
        resources_to_check.sort()

        project_limits = self.get_project_limits(project_id,
                                                 resources_to_check)
        current_usage = self.get_project_usage(project_id,
                                               resources_to_check)

        self._utils.enforce_limits(project_id, project_limits,
                                   current_usage, deltas)


class _StrictTwoLevelEnforcer:

    name = 'strict-two-level'

    def __init__(self, usage_callback, cache=True):
        self._usage_callback = usage_callback

    def get_registered_limits(self, resources_to_check):
        raise NotImplementedError()

    def get_project_limits(self, project_id, resources_to_check):
        raise NotImplementedError()

    def get_project_usage(self, project_id, resources_to_check):
        raise NotImplementedError()

    def enforce(self, project_id, deltas):
        raise NotImplementedError()


_MODELS = [_FlatEnforcer, _StrictTwoLevelEnforcer]


class _LimitNotFound(Exception):
    def __init__(self, resource):
        msg = "Can't find the limit for resource {resource}".format(
            resource=resource)
        self.resource = resource
        super().__init__(msg)


class _EnforcerUtils:
    """Logic common used by multiple enforcers"""

    def __init__(self, cache=True):
        self.connection = _get_keystone_connection()
        self.should_cache = cache
        # {project_id: {resource_name: project_limit}}
        self.plimit_cache = defaultdict(dict)
        # {resource_name: registered_limit}
        self.rlimit_cache = {}

        self._endpoint = self._get_endpoint()
        self._service_id = self._endpoint.service_id
        self._region_id = self._endpoint.region_id

    def _get_endpoint(self):
        endpoint = self._get_endpoint_by_id()
        if endpoint is not None:
            return endpoint

        return self._get_endpoint_by_service_lookup()

    def _get_endpoint_by_id(self):
        endpoint_id = CONF.oslo_limit.endpoint_id
        if endpoint_id is None:
            return None

        try:
            endpoint = self.connection.get_endpoint(endpoint_id)
        except os_exceptions.ResourceNotFound:
            raise ValueError("Can't find endpoint for %s" % endpoint_id)
        return endpoint

    def _get_endpoint_by_service_lookup(self):
        service_type = CONF.oslo_limit.endpoint_service_type
        service_name = CONF.oslo_limit.endpoint_service_name
        if not service_type and not service_name:
            raise ValueError(
                "Either service_type or service_name should be set")

        try:
            services = self.connection.services(type=service_type,
                                                name=service_name)
            if len(services) > 1:
                raise ValueError("Multiple services found")
            service_id = services[0].id
        except os_exceptions.ResourceNotFound:
            raise ValueError("Service not found")

        if CONF.oslo_limit.endpoint_region_name is not None:
            try:
                regions = self.connection.regions(
                    name=CONF.oslo_limit.endpoint_region_name)
                if len(regions) > 1:
                    raise ValueError("Multiple regions found")
                region_id = regions[0].id
            except os_exceptions.ResourceNotFound:
                raise ValueError("Region not found")
        else:
            region_id = None

        try:
            endpoints = self.connection.endpoints(
                service_id=service_id, region_id=region_id,
                interface=CONF.oslo_limit.endpoint_interface,
            )
        except os_exceptions.ResourceNotFound:
            raise ValueError("Endpoint not found")

        if len(endpoints) > 1:
            raise ValueError("Multiple endpoints found")

        return endpoints[0]

    @staticmethod
    def enforce_limits(project_id, limits, current_usage, deltas):
        """Check that proposed usage is not over given limits

        :param project_id: project being checked or None
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

    def _get_registered_limits(self):
        registered_limits = []
        reg_limits = self.connection.registered_limits(
            service_id=self._service_id, region_id=self._region_id)
        for reg_limit in reg_limits:
            name, limit = reg_limit.resource_name, reg_limit.default_limit
            registered_limits.append((name, limit))
            if self.should_cache:
                self.rlimit_cache[name] = reg_limit
        return registered_limits

    def get_registered_limits(self, resource_names):
        """Get all the default limits for a given resource name list

        :param resource_names: list of resource_name strings
        :return: list of (resource_name, limit) pairs
        """
        # If None was passed for resource_names, get and return all of the
        # registered limits.
        if resource_names is None:
            return self._get_registered_limits()

        # Using a list to preserve the resource_name order
        registered_limits = []
        for resource_name in resource_names:
            reg_limit = self._get_registered_limit(resource_name)
            if reg_limit:
                limit = reg_limit.default_limit
            else:
                limit = 0
            registered_limits.append((resource_name, limit))

        return registered_limits

    def _get_project_limits(self, project_id):
        if project_id is None:
            # If we were to pass None, we would receive limits for all projects
            # and we would have to return {project_id: [(name, limit), ...]}
            # which would be inconsistent with the return format of the other
            # methods.
            raise ValueError('project_id must not be None')

        project_limits = []
        proj_limits = self.connection.limits(
            service_id=self._service_id, region_id=self._region_id,
            project_id=project_id)
        for proj_limit in proj_limits:
            name, limit = proj_limit.resource_name, proj_limit.resource_limit
            project_limits.append((name, limit))
            if self.should_cache:
                self.plimit_cache[project_id][name] = proj_limit
        return project_limits

    def get_project_limits(self, project_id, resource_names):
        """Get all the limits for given project a resource_name list

        If a limit is not found, it will be considered to be zero
        (i.e. no quota)

        :param project_id: project being checked or None
        :param resource_names: list of resource_name strings
        :return: list of (resource_name,limit) pairs
        """
        # If None was passed for resource_names, get and return all of the
        # limits.
        if resource_names is None:
            return self._get_project_limits(project_id)

        # Using a list to preserver the resource_name order
        project_limits = []
        for resource_name in resource_names:
            try:
                limit = self._get_limit(project_id, resource_name)
            except _LimitNotFound:
                limit = 0
            project_limits.append((resource_name, limit))

        return project_limits

    def _get_limit(self, project_id, resource_name):
        # If we are configured to cache limits, look in the cache first and use
        # the cached value if there is one. Else, retrieve the limit and add it
        # to the cache. Do this for both project limits and registered limits.

        # Look for a project limit first.
        project_limit = (self._get_project_limit(project_id, resource_name)
                         if project_id is not None else None)

        if project_limit:
            return project_limit.resource_limit

        # If there is no project limit, look for a registered limit.
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
        # Look in the cache first.
        if (project_id in self.plimit_cache and
                resource_name in self.plimit_cache[project_id]):
            return self.plimit_cache[project_id][resource_name]

        # Get the limits from keystone.
        limits = self.connection.limits(
            service_id=self._service_id,
            region_id=self._region_id,
            project_id=project_id)
        limit = None
        for pl in limits:
            # NOTE(melwitt): If project_id None was passed in, it's possible
            # there will be multiple limits for the same resource (from various
            # projects), so keep the existing oslo.limit behavior and return
            # the first one we find. This could be considered to be a bug.
            if limit is None and pl.resource_name == resource_name:
                limit = pl
            if self.should_cache:
                self.plimit_cache[project_id][pl.resource_name] = pl

        return limit

    def _get_registered_limit(self, resource_name):
        # Look in the cache first.
        if resource_name in self.rlimit_cache:
            return self.rlimit_cache[resource_name]

        # Get the limits from keystone.
        reg_limits = self.connection.registered_limits(
            service_id=self._service_id,
            region_id=self._region_id)
        reg_limit = None
        for rl in reg_limits:
            if rl.resource_name == resource_name:
                reg_limit = rl
            # Cache the limit if configured.
            if self.should_cache:
                self.rlimit_cache[rl.resource_name] = rl

        return reg_limit
