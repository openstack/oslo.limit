#    Copyright 2021 Red Hat, Inc
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from unittest import mock

import fixtures as fixtures

from openstack.identity.v3 import endpoint
from openstack.identity.v3 import limit as keystone_limit


class LimitFixture(fixtures.Fixture):
    def __init__(self, reglimits, projlimits):
        """A fixture for testing code that relies on Keystone Unified Limits.

        :param reglimits: A dictionary of {resource_name: limit} values to
                          simulate registered limits in keystone.
        :type reglimits: dict
        :param projlimits: A dictionary of dictionaries defining per-project
                           limits like {project_id: {resource_name: limit}}.
                           As in reality, only per-project overrides need be
                           provided here; any unmentioned projects or
                           resources will take the registered limit defaults.
        :type reglimits: dict
        """
        self.reglimits = reglimits
        self.projlimits = projlimits

    def setUp(self):
        super(LimitFixture, self).setUp()

        # We mock our own cached connection to Keystone
        self.mock_conn = mock.MagicMock()
        self.useFixture(fixtures.MockPatch('oslo_limit.limit._SDK_CONNECTION',
                                           new=self.mock_conn))

        # Use a flat enforcement model
        mock_gem = self.useFixture(
            fixtures.MockPatch('oslo_limit.limit.Enforcer.'
                               '_get_enforcement_model')).mock
        mock_gem.return_value = 'flat'

        # Fake keystone endpoint; no per-service limit distinction
        fake_endpoint = endpoint.Endpoint()
        fake_endpoint.service_id = "service_id"
        fake_endpoint.region_id = "region_id"
        self.mock_conn.get_endpoint.return_value = fake_endpoint

        def fake_limits(service_id, region_id, resource_name, project_id=None):
            this_limit = keystone_limit.Limit()
            this_limit.resource_name = resource_name
            if project_id is None:
                this_limit.default_limit = self.reglimits.get(resource_name)
                if this_limit.default_limit is None:
                    return iter([None])
            else:
                this_limit.resource_limit = \
                    self.projlimits.get(project_id, {}).get(resource_name)
                if this_limit.resource_limit is None:
                    return iter([None])

            return iter([this_limit])

        self.mock_conn.limits.side_effect = fake_limits
        self.mock_conn.registered_limits.side_effect = fake_limits
