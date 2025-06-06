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

from unittest import mock
import uuid

from openstack import exceptions as os_exceptions
from openstack.identity.v3 import endpoint
from openstack.identity.v3 import limit as klimit
from openstack.identity.v3 import region
from openstack.identity.v3 import registered_limit
from openstack.identity.v3 import service
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslotest import base

from oslo_limit import exception
from oslo_limit import fixture
from oslo_limit import limit
from oslo_limit import opts

CONF = cfg.CONF


class TestEnforcer(base.BaseTestCase):

    def setUp(self):
        super().setUp()
        self.deltas = dict()
        self.config_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config_fixture.config(
            group='oslo_limit',
            auth_type='password'
        )
        self.config_fixture.config(
            group='oslo_limit',
            endpoint_id='ENDPOINT_ID'
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

    def _get_usage_for_project(self, project_id, resource_names):
        return {"a": 1}

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
        invalid_delta_types = [uuid.uuid4().hex, 5, 5.1, True, [], None, {}]
        enforcer = limit.Enforcer(self._get_usage_for_project)

        for invalid_delta in invalid_delta_types:
            self.assertRaises(
                ValueError,
                enforcer.enforce,
                project_id,
                invalid_delta
            )

    def test_project_id_must_be_a_string(self):
        enforcer = limit.Enforcer(self._get_usage_for_project)
        invalid_delta_types = [{}, 5, 5.1, True, False, [], None, ""]
        for invalid_project_id in invalid_delta_types:
            self.assertRaises(
                ValueError,
                enforcer.enforce,
                invalid_project_id,
                {}
            )

    def test_set_model_impl(self):
        enforcer = limit.Enforcer(self._get_usage_for_project)
        self.assertIsInstance(enforcer.model, limit._FlatEnforcer)

    def test_get_model_impl(self):
        json = mock.MagicMock()
        limit._SDK_CONNECTION.get.return_value = json

        json.json.return_value = {"model": {"name": "flat"}}
        enforcer = limit.Enforcer(self._get_usage_for_project)
        flat_impl = enforcer._get_model_impl(self._get_usage_for_project)
        self.assertIsInstance(flat_impl, limit._FlatEnforcer)

        json.json.return_value = {"model": {"name": "strict-two-level"}}
        flat_impl = enforcer._get_model_impl(self._get_usage_for_project)
        self.assertIsInstance(flat_impl, limit._StrictTwoLevelEnforcer)

        json.json.return_value = {"model": {"name": "foo"}}
        e = self.assertRaises(ValueError, enforcer._get_model_impl,
                              self._get_usage_for_project)
        self.assertEqual("enforcement model foo is not supported", str(e))

    @mock.patch.object(limit._FlatEnforcer, "enforce")
    def test_enforce(self, mock_enforce):
        enforcer = limit.Enforcer(self._get_usage_for_project)
        project_id = uuid.uuid4().hex
        deltas = {"a": 1}

        enforcer.enforce(project_id, deltas)

        mock_enforce.assert_called_once_with(project_id, deltas)

    @mock.patch.object(limit._EnforcerUtils, "get_project_limits")
    def test_calculate_usage(self, mock_get_limits):
        mock_usage = mock.MagicMock()
        mock_usage.return_value = {'a': 1, 'b': 2}

        project_id = uuid.uuid4().hex
        mock_get_limits.return_value = [('a', 10), ('b', 5)]

        expected = {
            'a': limit.ProjectUsage(10, 1),
            'b': limit.ProjectUsage(5, 2),
        }

        enforcer = limit.Enforcer(mock_usage)
        self.assertEqual(expected, enforcer.calculate_usage(project_id,
                                                            ['a', 'b']))

    @mock.patch.object(limit._EnforcerUtils, "_get_project_limit")
    @mock.patch.object(limit._EnforcerUtils, "_get_registered_limit")
    def test_calculate_and_enforce_some_missing(self, mock_get_reglimit,
                                                mock_get_limit):
        # Registered and project limits for a and b, c is unregistered
        reg_limits = {'a': mock.MagicMock(default_limit=10),
                      'b': mock.MagicMock(default_limit=10)}
        prj_limits = {('bar', 'b'): mock.MagicMock(resource_limit=6)}
        mock_get_reglimit.side_effect = lambda r: reg_limits.get(r)
        mock_get_limit.side_effect = lambda p, r: prj_limits.get((p, r))

        # Regardless, we have usage for all three
        mock_usage = mock.MagicMock()
        mock_usage.return_value = {'a': 5, 'b': 5, 'c': 5}

        enforcer = limit.Enforcer(mock_usage)

        # When we calculate usage, we should expect the default limit
        # of zero for the unregistered limit
        expected = {
            'a': limit.ProjectUsage(10, 5),
            'b': limit.ProjectUsage(6, 5),
            'c': limit.ProjectUsage(0, 5),
        }
        self.assertEqual(expected,
                         enforcer.calculate_usage('bar', ['a', 'b', 'c']))

        # Make sure that if we enforce, we get the expected behavior
        # of c being considered to be zero
        self.assertRaises(exception.ProjectOverLimit,
                          enforcer.enforce, 'bar', {'a': 1, 'b': 0, 'c': 1})

    def test_calculate_usage_bad_params(self):
        enforcer = limit.Enforcer(mock.MagicMock())

        # Non-string project_id
        self.assertRaises(ValueError,
                          enforcer.calculate_usage,
                          123, ['foo'])

        # Zero-length resources_to_check
        self.assertRaises(ValueError,
                          enforcer.calculate_usage,
                          'project', [])

        # Non-sequence resources_to_check
        self.assertRaises(ValueError,
                          enforcer.calculate_usage,
                          'project', 123)

        # Invalid non-string value in resources_to_check
        self.assertRaises(ValueError,
                          enforcer.calculate_usage,
                          'project', ['a', 123, 'b'])

    @mock.patch.object(limit._EnforcerUtils, "get_registered_limits")
    def test_get_registered_limits(self, mock_get_limits):
        mock_get_limits.return_value = [("a", 1), ("b", 0), ("c", 2)]

        enforcer = limit.Enforcer(lambda: None)
        limits = enforcer.get_registered_limits(["a", "b", "c"])

        mock_get_limits.assert_called_once_with(["a", "b", "c"])
        self.assertEqual(mock_get_limits.return_value, limits)

    @mock.patch.object(limit._EnforcerUtils, "get_project_limits")
    def test_get_project_limits(self, mock_get_limits):
        project_id = uuid.uuid4().hex
        mock_get_limits.return_value = [("a", 1), ("b", 0), ("c", 2)]

        enforcer = limit.Enforcer(lambda: None)
        limits = enforcer.get_project_limits(project_id, ["a", "b", "c"])

        mock_get_limits.assert_called_once_with(project_id, ["a", "b", "c"])
        self.assertEqual(mock_get_limits.return_value, limits)

    def test_calculate_usage_cache(self, cache=True):
        project_id = uuid.uuid4().hex
        fix = self.useFixture(fixture.LimitFixture(
            {'a': 5, 'b': 7, 'c': 8, 'd': 3},
            {project_id: {'a': 2, 'b': 4}, 'other': {'a': 1, 'b': 2}}))
        mock_usage = mock.MagicMock()
        mock_usage.return_value = {'a': 1, 'b': 3, 'c': 2, 'd': 0}

        enforcer = limit.Enforcer(mock_usage, cache=cache)
        expected = {
            'a': limit.ProjectUsage(2, 1),
            'b': limit.ProjectUsage(4, 3),
            'c': limit.ProjectUsage(8, 2),
            'd': limit.ProjectUsage(3, 0),
        }
        self.assertEqual(
            expected,
            enforcer.calculate_usage(project_id, ['a', 'b', 'c', 'd']))

        # If caching is enabled, there should be three calls to the GET /limits
        # API: one for 'a' and 'b' and two because of cache misses for 'c' and
        # 'd' (the project_id has not set a per-project limit for 'c' or 'd',
        # so they will not be cached for the project).
        # If caching is disabled, there should be four calls to the GET
        # /limits API, one for each of 'a', 'b', 'c', and 'd'.
        expected_count = 3 if cache else 4
        self.assertEqual(expected_count, fix.mock_conn.limits.call_count)

        # If caching is enabled, there should be one call to the GET
        # /registered_limits API for 'c' and 'd'.
        # If caching is disabled, there should be two calls to the GET
        # /registered_limits API, one for each of 'c' and 'd'.
        expected_count = 1 if cache else 2
        self.assertEqual(
            expected_count, fix.mock_conn.registered_limits.call_count)

    def test_calculate_usage_no_cache(self):
        self.test_calculate_usage_cache(cache=False)


class TestFlatEnforcer(base.BaseTestCase):
    def setUp(self):
        super().setUp()
        self.config_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config_fixture.config(
            group='oslo_limit',
            endpoint_id='ENDPOINT_ID'
        )
        opts.register_opts(CONF)
        self.mock_conn = mock.MagicMock()
        limit._SDK_CONNECTION = self.mock_conn

    @mock.patch.object(limit._EnforcerUtils, "get_registered_limits")
    def test_get_registered_limits(self, mock_get_limits):
        mock_get_limits.return_value = [("a", 1), ("b", 0), ("c", 2)]

        enforcer = limit._FlatEnforcer(lambda: None)
        limits = enforcer.get_registered_limits(["a", "b", "c"])

        mock_get_limits.assert_called_once_with(["a", "b", "c"])
        self.assertEqual(mock_get_limits.return_value, limits)

    @mock.patch.object(limit._EnforcerUtils, "get_project_limits")
    def test_get_project_limits(self, mock_get_limits):
        project_id = uuid.uuid4().hex
        mock_get_limits.return_value = [("a", 1), ("b", 0), ("c", 2)]

        enforcer = limit._FlatEnforcer(lambda: None)
        limits = enforcer.get_project_limits(project_id, ["a", "b", "c"])

        mock_get_limits.assert_called_once_with(project_id, ["a", "b", "c"])
        self.assertEqual(mock_get_limits.return_value, limits)

    @mock.patch.object(limit._EnforcerUtils, "get_project_limits")
    def test_enforce(self, mock_get_limits):
        mock_usage = mock.MagicMock()

        project_id = uuid.uuid4().hex
        deltas = {"a": 1, "b": 1}
        mock_get_limits.return_value = [("a", 1), ("b", 2)]
        mock_usage.return_value = {"a": 0, "b": 1}

        enforcer = limit._FlatEnforcer(mock_usage)
        enforcer.enforce(project_id, deltas)

        self.mock_conn.get_endpoint.assert_called_once_with('ENDPOINT_ID')
        mock_get_limits.assert_called_once_with(project_id, ["a", "b"])
        mock_usage.assert_called_once_with(project_id, ["a", "b"])

    @mock.patch.object(limit._EnforcerUtils, "get_project_limits")
    def test_enforce_raises_on_over(self, mock_get_limits):
        mock_usage = mock.MagicMock()

        project_id = uuid.uuid4().hex
        deltas = {"a": 2, "b": 1}
        mock_get_limits.return_value = [("a", 1), ("b", 2)]
        mock_usage.return_value = {"a": 0, "b": 1}

        enforcer = limit._FlatEnforcer(mock_usage)
        e = self.assertRaises(exception.ProjectOverLimit, enforcer.enforce,
                              project_id, deltas)
        expected = ("Project %s is over a limit for "
                    "[Resource a is over limit of 1 due to current usage 0 "
                    "and delta 2]")
        self.assertEqual(expected % project_id, str(e))
        self.assertEqual(project_id, e.project_id)
        self.assertEqual(1, len(e.over_limit_info_list))
        over_a = e.over_limit_info_list[0]
        self.assertEqual("a", over_a.resource_name)
        self.assertEqual(1, over_a.limit)
        self.assertEqual(0, over_a.current_usage)
        self.assertEqual(2, over_a.delta)

    @mock.patch.object(limit._EnforcerUtils, "_get_project_limit")
    @mock.patch.object(limit._EnforcerUtils, "_get_registered_limit")
    def test_enforce_raises_on_missing_limit(self, mock_get_reglimit,
                                             mock_get_limit):
        def mock_usage(*a):
            return {'a': 1, 'b': 1}

        project_id = uuid.uuid4().hex
        deltas = {"a": 0, "b": 0}
        mock_get_reglimit.return_value = None
        mock_get_limit.return_value = None

        enforcer = limit._FlatEnforcer(mock_usage)
        self.assertRaises(exception.ProjectOverLimit, enforcer.enforce,
                          project_id, deltas)

        self.assertRaises(exception.ProjectOverLimit, enforcer.enforce,
                          None, deltas)


class TestEnforcerUtils(base.BaseTestCase):
    def setUp(self):
        super().setUp()
        self.config_fixture = self.useFixture(config_fixture.Config(CONF))
        self.config_fixture.config(
            group='oslo_limit',
            endpoint_id='ENDPOINT_ID'
        )
        opts.register_opts(CONF)
        self.mock_conn = mock.MagicMock()
        limit._SDK_CONNECTION = self.mock_conn

    def test_get_endpoint(self):
        fake_endpoint = endpoint.Endpoint()
        self.mock_conn.get_endpoint.return_value = fake_endpoint

        utils = limit._EnforcerUtils()

        self.assertEqual(fake_endpoint, utils._endpoint)
        self.mock_conn.get_endpoint.assert_called_once_with('ENDPOINT_ID')
        self.mock_conn.services.assert_not_called()
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_no_id(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.mock_conn.get_endpoint.side_effect = \
            os_exceptions.ResourceNotFound

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )
        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_not_called()
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_missing(self):
        self.mock_conn.get_endpoint.side_effect = \
            os_exceptions.ResourceNotFound

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )
        self.mock_conn.get_endpoint.assert_called_once_with('ENDPOINT_ID')
        self.mock_conn.services.assert_not_called()
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_lookup_without_service_opts(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_not_called()
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_lookup(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        fake_service = service.Service(id='SERVICE_ID')
        self.mock_conn.services.return_value = [fake_service]
        fake_endpoint = endpoint.Endpoint()
        self.mock_conn.endpoints.return_value = [fake_endpoint]

        utils = limit._EnforcerUtils()

        self.assertEqual(fake_endpoint, utils._endpoint)
        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.endpoints.assert_called_once_with(
            service_id='SERVICE_ID', region_id=None, interface='publicURL')

    def test_get_endpoint_lookup_multiple_endpoints(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        fake_service = service.Service(id='SERVICE_ID')
        self.mock_conn.services.return_value = [fake_service]
        self.mock_conn.endpoints.return_value = [
            endpoint.Endpoint(), endpoint.Endpoint()
        ]

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.endpoints.assert_called_once_with(
            service_id='SERVICE_ID', region_id=None, interface='publicURL')

    def test_get_endpoint_lookup_endpoint_not_found(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        fake_service = service.Service(id='SERVICE_ID')
        self.mock_conn.services.return_value = [fake_service]
        self.mock_conn.endpoints.side_effect = os_exceptions.ResourceNotFound

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.endpoints.assert_called_once_with(
            service_id='SERVICE_ID', region_id=None, interface='publicURL')

    def test_get_endpoint_lookup_multiple_service(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        self.mock_conn.services.side_effect = [
            service.Service(id='SERVICE_ID1'),
            service.Service(id='SERVICE_ID2')
        ]

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_lookup_service_not_found(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        self.mock_conn.services.side_effect = os_exceptions.ResourceNotFound

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_lookup_with_region(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_region_name='regionOne'
        )
        fake_service = service.Service(id='SERVICE_ID')
        self.mock_conn.services.return_value = [fake_service]
        fake_endpoint = endpoint.Endpoint()
        self.mock_conn.endpoints.return_value = [fake_endpoint]
        fake_region = region.Region(id='REGION_ID')
        self.mock_conn.regions.return_value = [fake_region]

        utils = limit._EnforcerUtils()

        self.assertEqual(fake_endpoint, utils._endpoint)
        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.regions.assert_called_once_with(name='regionOne')
        self.mock_conn.endpoints.assert_called_once_with(
            service_id='SERVICE_ID', region_id='REGION_ID',
            interface='publicURL')

    def test_get_endpoint_lookup_with_region_not_found(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_region_name='regionOne'
        )
        fake_service = service.Service(id='SERVICE_ID')
        self.mock_conn.services.return_value = [fake_service]
        fake_endpoint = endpoint.Endpoint()
        self.mock_conn.endpoints.return_value = [fake_endpoint]
        self.mock_conn.regions.side_effect = os_exceptions.ResourceNotFound

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.regions.assert_called_once_with(name='regionOne')
        self.mock_conn.endpoints.assert_not_called()

    def test_get_endpoint_lookup_with_mutliple_regions(self):
        self.config_fixture.config(group='oslo_limit', endpoint_id=None)
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_type='SERVICE_TYPE'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_service_name='SERVICE_NAME'
        )
        self.config_fixture.config(
            group='oslo_limit', endpoint_region_name='regionOne'
        )
        fake_service = service.Service(id='SERVICE_ID')
        self.mock_conn.services.return_value = [fake_service]
        fake_endpoint = endpoint.Endpoint()
        self.mock_conn.endpoints.return_value = [fake_endpoint]
        self.mock_conn.regions.return_value = [
            region.Region(id='REGION_ID1'), region.Region(id='REGION_ID2')]

        self.assertRaises(
            ValueError,
            limit._EnforcerUtils
        )

        self.mock_conn.get_endpoint.assert_not_called()
        self.mock_conn.services.assert_called_once_with(type='SERVICE_TYPE',
                                                        name='SERVICE_NAME')
        self.mock_conn.regions.assert_called_once_with(name='regionOne')
        self.mock_conn.endpoints.assert_not_called()

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

    def test_get_registered_limits(self):
        fake_endpoint = endpoint.Endpoint(service_id='service_id',
                                          region_id='region_id')
        self.mock_conn.get_endpoint.return_value = fake_endpoint

        # a and c have limits, b doesn't have one
        empty_iterator = iter([])

        a = registered_limit.RegisteredLimit()
        a.resource_name = "a"
        a.default_limit = 1
        a_iterator = iter([a])

        c = registered_limit.RegisteredLimit()
        c.resource_name = "c"
        c.default_limit = 2
        c_iterator = iter([c])

        self.mock_conn.registered_limits.side_effect = [a_iterator,
                                                        empty_iterator,
                                                        c_iterator]

        utils = limit._EnforcerUtils()
        limits = utils.get_registered_limits(["a", "b", "c"])
        self.assertEqual([('a', 1), ('b', 0), ('c', 2)], limits)

    def test_get_project_limits(self):
        fake_endpoint = endpoint.Endpoint(service_id='service_id',
                                          region_id='region_id')
        self.mock_conn.get_endpoint.return_value = fake_endpoint
        project_id = uuid.uuid4().hex

        # a is a project limit, b, c and d don't have one
        empty_iterator = iter([])
        a = klimit.Limit()
        a.resource_name = "a"
        a.resource_limit = 1
        a_iterator = iter([a])
        self.mock_conn.limits.side_effect = [a_iterator, empty_iterator,
                                             empty_iterator, empty_iterator]

        # b has a limit, but c and d doesn't, a isn't ever checked
        b = registered_limit.RegisteredLimit()
        b.resource_name = "b"
        b.default_limit = 2
        b_iterator = iter([b])
        self.mock_conn.registered_limits.side_effect = [b_iterator,
                                                        empty_iterator,
                                                        empty_iterator]

        utils = limit._EnforcerUtils()
        limits = utils.get_project_limits(project_id, ["a", "b"])
        self.assertEqual([('a', 1), ('b', 2)], limits)

        limits = utils.get_project_limits(project_id, ["c", "d"])
        self.assertEqual([('c', 0), ('d', 0)], limits)

    def test__get_project_limit_cache(self, cache=True):
        # Registered limit = 5 and project limit = 3
        project_id = uuid.uuid4().hex
        fix = self.useFixture(
            fixture.LimitFixture({'foo': 5}, {project_id: {'foo': 3}}))

        utils = limit._EnforcerUtils(cache=cache)
        foo_limit = utils._get_project_limit(project_id, 'foo')

        self.assertEqual(3, foo_limit.resource_limit)
        self.assertEqual(1, fix.mock_conn.limits.call_count)

        # Second call should be cached, so call_count for project limits should
        # remain 1. When cache is disabled, it should increase to 2
        foo_limit = utils._get_project_limit(project_id, 'foo')
        count = 1 if cache else 2
        self.assertEqual(count, fix.mock_conn.limits.call_count)

    def test__get_project_limit_cache_no_cache(self):
        self.test__get_project_limit_cache(cache=False)

    def test__get_registered_limit_cache(self, cache=True):
        # Registered limit = 5 and project limit = 3
        project_id = uuid.uuid4().hex
        fix = self.useFixture(
            fixture.LimitFixture({'foo': 5}, {project_id: {'foo': 3}}))

        utils = limit._EnforcerUtils(cache=cache)
        foo_limit = utils._get_registered_limit('foo')

        self.assertEqual(5, foo_limit.default_limit)
        self.assertEqual(1, fix.mock_conn.registered_limits.call_count)

        # Second call should be cached, so call_count for project limits should
        # remain 1. When cache is disabled, it should increase to 2
        foo_limit = utils._get_registered_limit('foo')
        count = 1 if cache else 2
        self.assertEqual(count, fix.mock_conn.registered_limits.call_count)

    def test__get_registered_limit_cache_no_cache(self):
        self.test__get_registered_limit_cache(cache=False)

    def test_get_limit_cache(self, cache=True):
        # No project limit and registered limit = 5
        fix = self.useFixture(fixture.LimitFixture({'foo': 5}, {}))
        project_id = uuid.uuid4().hex

        utils = limit._EnforcerUtils(cache=cache)
        foo_limit = utils._get_limit(project_id, 'foo')

        self.assertEqual(5, foo_limit)
        self.assertEqual(1, fix.mock_conn.registered_limits.call_count)

        # Second call should be cached, so call_count for registered limits
        # should remain 1. When cache is disabled, it should increase to 2
        foo_limit = utils._get_limit(project_id, 'foo')
        self.assertEqual(5, foo_limit)
        count = 1 if cache else 2
        self.assertEqual(count, fix.mock_conn.registered_limits.call_count)

        # Add a project limit = 1
        fix.projlimits[project_id] = {'foo': 1}

        foo_limit = utils._get_limit(project_id, 'foo')

        self.assertEqual(1, foo_limit)
        # Project limits should have been queried 3 times total, once per
        # _get_limit call
        self.assertEqual(3, fix.mock_conn.limits.call_count)

        # Fourth call should be cached, so call_count for project limits should
        # remain 3. When cache is disabled, it should increase to 4
        foo_limit = utils._get_limit(project_id, 'foo')
        self.assertEqual(1, foo_limit)
        count = 3 if cache else 4
        self.assertEqual(count, fix.mock_conn.limits.call_count)

    def test_get_limit_no_cache(self):
        self.test_get_limit_cache(cache=False)

    def test_get_limit(self):
        utils = limit._EnforcerUtils(cache=False)

        mgpl = mock.MagicMock()
        mgrl = mock.MagicMock()
        with mock.patch.multiple(utils, _get_project_limit=mgpl,
                                 _get_registered_limit=mgrl):
            # With a project, we expect the project limit to be
            # fetched. If present, we never check the registered limit.
            utils._get_limit('project', 'foo')
            mgrl.assert_not_called()
            mgpl.assert_called_once_with('project', 'foo')

            mgrl.reset_mock()
            mgpl.reset_mock()

            # With a project, we expect the project limit to be
            # fetched. If absent, we check the registered limit.
            mgpl.return_value = None
            utils._get_limit('project', 'foo')
            mgrl.assert_called_once_with('foo')
            mgpl.assert_called_once_with('project', 'foo')

            mgrl.reset_mock()
            mgpl.reset_mock()

            # With no project, we expect to get registered limit but
            # not project limit
            utils._get_limit(None, 'foo')
            mgrl.assert_called_once_with('foo')
            mgpl.assert_not_called()

    def test_get_registered_limits_resource_names_none(self):
        fix = self.useFixture(fixture.LimitFixture({'foo': 5, 'bar': 7}, {}))

        utils = limit._EnforcerUtils()
        limits = utils.get_registered_limits(None)

        self.assertEqual([('foo', 5), ('bar', 7)], limits)
        fix.mock_conn.registered_limits.assert_called_once()

        # Call again with resource names to test caching.
        limits = utils.get_registered_limits(['foo', 'bar'])

        self.assertEqual([('foo', 5), ('bar', 7)], limits)
        fix.mock_conn.registered_limits.assert_called_once()

    def test_get_registered_limits_resource_names_none_no_cache(self):
        fix = self.useFixture(fixture.LimitFixture({'foo': 5, 'bar': 7}, {}))

        utils = limit._EnforcerUtils(cache=False)
        limits = utils.get_registered_limits(None)

        self.assertEqual([('foo', 5), ('bar', 7)], limits)
        fix.mock_conn.registered_limits.assert_called_once()

        # Call again with resource names to test caching.
        limits = utils.get_registered_limits(['foo', 'bar'])

        self.assertEqual([('foo', 5), ('bar', 7)], limits)
        # First call gets all limits, then one call per resource name.
        self.assertEqual(3, fix.mock_conn.registered_limits.call_count)

    def test_get_registered_limits_resource_names(self):
        fix = self.useFixture(fixture.LimitFixture({'foo': 5, 'bar': 7}, {}))

        utils = limit._EnforcerUtils()
        limits = utils.get_registered_limits(['foo', 'bar'])

        self.assertEqual([('foo', 5), ('bar', 7)], limits)
        fix.mock_conn.registered_limits.assert_called_once()

    def test_get_registered_limits_resource_names_no_cache(self):
        fix = self.useFixture(fixture.LimitFixture({'foo': 5, 'bar': 7}, {}))

        utils = limit._EnforcerUtils(cache=False)
        limits = utils.get_registered_limits(['foo', 'bar'])

        self.assertEqual([('foo', 5), ('bar', 7)], limits)
        self.assertEqual(2, fix.mock_conn.registered_limits.call_count)

    def test_get_project_limits_resource_names_none_project_id_none(self):
        # We consider project_id None to be invalid for "get_project_limits"
        # because it would require us to make the return format for getting
        # project limits different than the format for registered limits.
        # [(name, limit), (name, limit), ...]
        utils = limit._EnforcerUtils()
        self.assertRaises(ValueError, utils.get_project_limits, None, None)

    def test_get_project_limits_resource_names_none(self):
        project_id = uuid.uuid4().hex
        fix = self.useFixture(fixture.LimitFixture(
            {'foo': 5, 'bar': 7},
            {project_id: {'foo': 2, 'bar': 4}, 'other': {'foo': 1, 'bar': 2}}))

        utils = limit._EnforcerUtils()
        limits = utils.get_project_limits(project_id, None)

        self.assertEqual([('foo', 2), ('bar', 4)], limits)
        fix.mock_conn.limits.assert_called_once()

        # Call again with resource names to test caching.
        limits = utils.get_project_limits(project_id, ['foo', 'bar'])

        self.assertEqual([('foo', 2), ('bar', 4)], limits)
        fix.mock_conn.limits.assert_called_once()

    def test_get_project_limits_resource_names_none_no_cache(self):
        project_id = uuid.uuid4().hex
        fix = self.useFixture(fixture.LimitFixture(
            {'foo': 5, 'bar': 7},
            {project_id: {'foo': 2, 'bar': 4}, 'other': {'foo': 1, 'bar': 2}}))

        utils = limit._EnforcerUtils(cache=False)
        limits = utils.get_project_limits(project_id, None)

        self.assertEqual([('foo', 2), ('bar', 4)], limits)
        fix.mock_conn.limits.assert_called_once()

        # Call again with resource names to test caching.
        limits = utils.get_project_limits(project_id, ['foo', 'bar'])

        self.assertEqual([('foo', 2), ('bar', 4)], limits)
        # First call gets all limits, then one call per resource name.
        self.assertEqual(3, fix.mock_conn.limits.call_count)

    def test_get_project_limits_resource_names(self):
        project_id = uuid.uuid4().hex
        fix = self.useFixture(fixture.LimitFixture(
            {'foo': 5, 'bar': 7},
            {project_id: {'foo': 2, 'bar': 4}, 'other': {'foo': 1, 'bar': 2}}))

        utils = limit._EnforcerUtils()
        limits = utils.get_project_limits(project_id, ['foo', 'bar'])

        self.assertEqual([('foo', 2), ('bar', 4)], limits)
        fix.mock_conn.limits.assert_called_once()

    def test_get_project_limits_resource_names_no_cache(self):
        project_id = uuid.uuid4().hex
        fix = self.useFixture(fixture.LimitFixture(
            {'foo': 5, 'bar': 7},
            {project_id: {'foo': 2, 'bar': 4}, 'other': {'foo': 1, 'bar': 2}}))

        utils = limit._EnforcerUtils(cache=False)
        limits = utils.get_project_limits(project_id, ['foo', 'bar'])

        self.assertEqual([('foo', 2), ('bar', 4)], limits)
        self.assertEqual(2, fix.mock_conn.limits.call_count)
