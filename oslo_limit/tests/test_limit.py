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

import uuid

from oslotest import base

from oslo_limit import limit


class TestEnforcer(base.BaseTestCase):

    def setUp(self):
        super(TestEnforcer, self).setUp()
        self.deltas = dict()

    def _get_usage_for_project(self, project_id):
        return 8

    def test_required_parameters(self):
        enforcer = limit.Enforcer(self.deltas)

        self.assertEqual(self.deltas, enforcer.deltas)
        self.assertIsNone(enforcer.callback)

    def test_optional_parameters(self):
        callback = self._get_usage_for_project
        enforcer = limit.Enforcer(self.deltas, callback=callback)

        self.assertEqual(self.deltas, enforcer.deltas)
        self.assertEqual(self._get_usage_for_project, enforcer.callback)

    def test_callback_must_be_callable(self):
        invalid_callback_types = [uuid.uuid4().hex, 5, 5.1]

        for invalid_callback in invalid_callback_types:
            self.assertRaises(
                ValueError,
                limit.Enforcer,
                self.deltas,
                callback=invalid_callback
            )

    def test_deltas_must_be_a_dictionary(self):
        invalid_delta_types = [uuid.uuid4().hex, 5, 5.1, True, False, []]

        for invalid_delta in invalid_delta_types:
            self.assertRaises(
                ValueError,
                limit.Enforcer,
                invalid_delta,
            )
