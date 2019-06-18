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

    def enforce(self, project_id, deltas, resource_filters=None):
        """Check resource usage against limits and request deltas.

        :param project_id: The project to check usage and enforce limits
                           against.
        :type project_id: string
        :param deltas: An dictionary containing resource names as keys and
                       requests resource quantities as values.
        :type deltas: dictionary
        :param resource_filters: A list of strings containing the resource
                                 names to filter the return values of the
                                 usage_callback. This is a performance
                                 optimization in the event the caller doesn't
                                 want the usage_callback to collect all
                                 resources owned by the service. By default,
                                 no resources will be filtered.

        """
        if not isinstance(project_id, six.text_type):
            msg = 'project_id must be a string.'
            raise ValueError(msg)
        if not isinstance(deltas, dict):
            msg = 'deltas must be a dictionary.'
            raise ValueError(msg)
        if resource_filters and not isinstance(resource_filters, list):
            msg = 'resource_filters must be a list.'
            raise ValueError(msg)
