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

from collections.abc import Collection
from unittest import mock
import uuid

import fixtures
from openstack import config
from openstack import connection
from openstack import utils as os_utils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslotest import base

from oslo_limit import exception
from oslo_limit import limit


CONF = cfg.CONF


class TestEnforcerFunctional(base.BaseTestCase):
    def setUp(self):
        super().setUp()
        self.config_fixture = self.useFixture(config_fixture.Config(CONF))

        admin_conn = connection.from_config(
            config=config.OpenStackConfig().get_one(
                cloud='devstack-system-admin'
            )
        )
        self.admin_conn = os_utils.ensure_service_version(
            admin_conn.identity, '3'
        )

        connection.from_config(
            config=config.OpenStackConfig().get_one(
                cloud='devstack-system-reader'
            )
        )
        self.reader_conn = os_utils.ensure_service_version(
            admin_conn.identity, '3'
        )

        self.useFixture(
            fixtures.MonkeyPatch(
                'oslo_limit.limit._get_keystone_connection',
                mock.Mock(return_value=self.reader_conn),
            )
        )
        self.service = self.admin_conn.create_service(
            name=uuid.uuid4().hex,
            type=uuid.uuid4().hex,
        )
        self.addCleanup(self.admin_conn.delete_service, self.service)

        self.region = next(iter(self.admin_conn.regions()))
        self.endpoint = self.admin_conn.create_endpoint(
            service_id=self.service.id,
            region=self.region,
            url='http://example.com/',
            interface='public',
            enabled=False,
        )
        self.addCleanup(self.admin_conn.delete_endpoint, self.endpoint)

        self.project = self.admin_conn.create_project(
            name=uuid.uuid4().hex,
        )
        self.addCleanup(self.admin_conn.delete_project, self.project)

        for i in range(2):
            rlimit = self.admin_conn.create_registered_limit(
                resource_name=f'rsc{i}',
                service_id=self.service.id,
                project_id=self.project.id,
                default_limit=5 + i,
            )
            self.addCleanup(self.admin_conn.delete_registered_limit, rlimit)

            plimit = self.admin_conn.create_limit(
                resource_name=f'rsc{i}',
                service_id=self.service.id,
                project_id=self.project.id,
                resource_limit=2 + i,
            )
            self.addCleanup(self.admin_conn.delete_limit, plimit)

    def _test_enforcer(self):
        def callback_func(
            project_id: str | None, resources: Collection[str]
        ) -> dict[str, int]:
            all_usage = {"rsc0": 1, "rsc1": 2, "rsc2": 3}
            return {rsc: all_usage[rsc] for rsc in resources}

        enforcer = limit.Enforcer(callback_func)

        self.assertEqual(
            [("rsc0", 5)],
            enforcer.get_registered_limits(['rsc0']),
        )
        self.assertEqual(
            [("rsc0", 5), ("rsc1", 6)],
            enforcer.get_registered_limits(['rsc0', 'rsc1']),
        )
        self.assertEqual(
            [("rsc0", 2)],
            enforcer.get_project_limits(self.project.id, ['rsc0']),
        )
        self.assertEqual(
            [("rsc0", 2), ("rsc1", 3)],
            enforcer.get_project_limits(self.project.id, ['rsc0', 'rsc1']),
        )
        self.assertEqual(
            {'rsc0': limit.ProjectUsage(2, 1)},
            enforcer.calculate_usage(self.project.id, ['rsc0']),
        )
        self.assertEqual(
            {
                'rsc0': limit.ProjectUsage(2, 1),
                'rsc1': limit.ProjectUsage(3, 2),
            },
            enforcer.calculate_usage(self.project.id, ['rsc0', 'rsc1']),
        )

        enforcer.enforce(self.project.id, {'rsc0': 1})
        self.assertRaises(
            exception.ProjectOverLimit,
            enforcer.enforce,
            self.project.id,
            {'rsc0': 2},
        )
        enforcer.enforce(self.project.id, {'rsc0': 1, 'rsc1': 1})
        self.assertRaises(
            exception.ProjectOverLimit,
            enforcer.enforce,
            self.project.id,
            {'rsc0': 2, 'rsc1': 1},
        )

    def test_enforcer_endpoint_id(self):
        self.config_fixture.config(
            group='oslo_limit', endpoint_id=self.endpoint.id
        )
        self._test_enforcer()

    def test_enforcer_endpoint_discovery(self):
        self.config_fixture.config(
            group='oslo_limit',
            endpoint_service_type=self.service.type,
            endpoint_service_name=self.service.name,
            endpoint_interface='public',
        )
        self._test_enforcer()

    def test_enforcer_endpoint_discovery_with_region(self):
        self.config_fixture.config(
            group='oslo_limit',
            endpoint_service_type=self.service.type,
            endpoint_service_name=self.service.name,
            endpoint_region_name=self.region.name,
            endpoint_interface='public',
        )
        self._test_enforcer()
