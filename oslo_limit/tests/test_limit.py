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

"""
test_limit
----------------------------------

Tests for `limit` module.
"""

import mock
import uuid

from openstack.identity.v3 import endpoint
from openstack.identity.v3 import limit as klimit
from openstack.identity.v3 import registered_limit
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslotest import base

from oslo_limit import exception
from oslo_limit import limit
from oslo_limit import opts

CONF = cfg.CONF


class TestEnforcer(base.BaseTestCase):

    def setUp(self):
        super(TestEnforcer, self).setUp()
        self.deltas = dict()
        self.config_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config_fixture.config(
            group='oslo_limit',
            auth_type='password'
        )
        opts.register_opts(CONF)
        self.config_fixture.config(
            group='oslo_limit',
            auth_url='http://identity.example.com'
        )

        limit._SDK_CONNECTION = mock.MagicMock()
        json = mock.MagicMock()
        json.json.return_value = {"model": {"name": "flat"}}
        limit._SDK_CONNECTION.get.return_value = json

    def _get_usage_for_project(self, project_id):
        return 8

    def test_required_parameters(self):
        enforcer = limit.Enforcer(self._get_usage_for_project)
        self.assertEqual(self._get_usage_for_project, enforcer.usage_callback)

    def test_usage_callback_must_be_callable(self):
        invalid_callback_types = [uuid.uuid4().hex, 5, 5.1]

        for invalid_callback in invalid_callback_types:
            self.assertRaises(
                ValueError,
                limit.Enforcer,
                invalid_callback
            )

    def test_deltas_must_be_a_dictionary(self):
        project_id = uuid.uuid4().hex
        invalid_delta_types = [uuid.uuid4().hex, 5, 5.1, True, False, []]
        enforcer = limit.Enforcer(self._get_usage_for_project)

        for invalid_delta in invalid_delta_types:
            self.assertRaises(
                ValueError,
                enforcer.enforce,
                project_id,
                invalid_delta
            )

    def test_set_model_impl(self):
        enforcer = limit.Enforcer(self._get_usage_for_project)
        self.assertIsInstance(enforcer.model, limit._FlatEnforcer)

    def test_get_model_impl(self):
        json = mock.MagicMock()
        limit._SDK_CONNECTION.get.return_value = json

        json.json.return_value = {"model": {"name": "flat"}}
        enforcer = limit.Enforcer(self._get_usage_for_project)
        flat_impl = enforcer._get_model_impl()
        self.assertIsInstance(flat_impl, limit._FlatEnforcer)

        json.json.return_value = {"model": {"name": "strict-two-level"}}
        flat_impl = enforcer._get_model_impl()
        self.assertIsInstance(flat_impl, limit._StrictTwoLevelEnforcer)

        json.json.return_value = {"model": {"name": "foo"}}
        e = self.assertRaises(ValueError, enforcer._get_model_impl)
        self.assertEqual("enforcement model foo is not supported", str(e))


class TestEnforcerUtils(base.BaseTestCase):
    def setUp(self):
        super(TestEnforcerUtils, self).setUp()
        self.mock_conn = mock.MagicMock()
        limit._SDK_CONNECTION = self.mock_conn

    def test_get_endpoint(self):
        fake_endpoint = endpoint.Endpoint()
        self.mock_conn.get_endpoint.return_value = fake_endpoint

        utils = limit._EnforcerUtils()

        self.assertEqual(fake_endpoint, utils._endpoint)
        self.mock_conn.get_endpoint.assert_called_once_with(None)

    def test_get_registered_limit_empty(self):
        self.mock_conn.registered_limits.return_value = iter([])

        utils = limit._EnforcerUtils()
        reg_limit = utils._get_registered_limit("foo")

        self.assertIsNone(reg_limit)

    def test_get_registered_limit(self):
        foo = registered_limit.RegisteredLimit()
        foo.resource_name = "foo"
        self.mock_conn.registered_limits.return_value = iter([foo])

        utils = limit._EnforcerUtils()
        reg_limit = utils._get_registered_limit("foo")

        self.assertEqual(foo, reg_limit)

    def test_get_project_limits(self):
        fake_endpoint = endpoint.Endpoint()
        fake_endpoint.service_id = "service_id"
        fake_endpoint.region_id = "region_id"
        self.mock_conn.get_endpoint.return_value = fake_endpoint
        project_id = uuid.uuid4().hex

        # a is a project limit, b and c don't have one
        empty_iterator = iter([])
        a = klimit.Limit()
        a.resource_name = "a"
        a.resource_limit = 1
        a_iterator = iter([a])
        self.mock_conn.limits.side_effect = [a_iterator, empty_iterator,
                                             empty_iterator]

        # b has a limit, but c doesn't, a isn't ever checked
        b = registered_limit.RegisteredLimit()
        b.resource_name = "b"
        b.default_limit = 2
        b_iterator = iter([b])
        self.mock_conn.registered_limits.side_effect = [b_iterator,
                                                        empty_iterator]

        utils = limit._EnforcerUtils()
        limits = utils.get_project_limits(project_id, ["a", "b"])
        self.assertEqual([('a', 1), ('b', 2)], limits)

        e = self.assertRaises(exception.LimitNotFound,
                              utils.get_project_limits,
                              project_id, ["c"])
        self.assertEqual("c", e.resource)
        self.assertEqual("service_id", e.service)
        self.assertEqual("region_id", e.region)
