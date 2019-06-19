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
import six

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
        :type callable function:

        """
        if not callable(usage_callback):
            msg = 'usage_callback must be a callable function.'
            raise ValueError(msg)

        self.usage_callback = usage_callback
        self.connection = _get_keystone_connection()
        self.model = self._get_model_impl()

    def _get_enforcement_model(self):
        """Query keystone for the configured enforcement model."""
        return self.connection.get('/limits/model').json()['model']['name']

    def _get_model_impl(self):
        """get the enforcement model based on configured model in keystone."""
        model = self._get_enforcement_model()
        for impl in _MODELS:
            if model == impl.name:
                return impl()
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

        """
        if not isinstance(project_id, six.text_type):
            msg = 'project_id must be a string.'
            raise ValueError(msg)
        if not isinstance(deltas, dict):
            msg = 'deltas must be a dictionary.'
            raise ValueError(msg)

        for k, v in iter(deltas.items()):
            if not isinstance(k, six.text_type):
                raise ValueError('resource name is not a string.')
            elif not isinstance(v, int):
                raise ValueError('resource limit is not an integer.')

        self.model.enforce(project_id, deltas)


class _FlatEnforcer(object):

    name = 'flat'

    def enforce(self, project_id, deltas):
        raise NotImplementedError()


class _StrictTwoLevelEnforcer(object):

    name = 'strict-two-level'

    def enforce(self, project_id, deltas):
        raise NotImplementedError()


_MODELS = [_FlatEnforcer, _StrictTwoLevelEnforcer]
