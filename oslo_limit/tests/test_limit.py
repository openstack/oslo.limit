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

from oslo_limit import limit
from oslotest import base


class TestProjectClaim(base.BaseTestCase):

    def test_required_parameters(self):
        resource_name = uuid.uuid4().hex
        project_id = uuid.uuid4().hex

        claim = limit.ProjectClaim(resource_name, project_id)

        self.assertEqual(resource_name, claim.resource_name)
        self.assertEqual(project_id, claim.project_id)
        self.assertIsNone(claim.quantity)

    def test_optional_parameters(self):
        resource_name = uuid.uuid4().hex
        project_id = uuid.uuid4().hex
        quantity = 10

        claim = limit.ProjectClaim(
            resource_name, project_id, quantity=quantity
        )

        self.assertEqual(resource_name, claim.resource_name)
        self.assertEqual(project_id, claim.project_id)
        self.assertEqual(quantity, claim.quantity)

    def test_resource_name_must_be_a_string(self):
        project_id = uuid.uuid4().hex
        invalid_resource_name_types = [
            True, False, [uuid.uuid4().hex], {'key': 'value'}, 1, 1.2
        ]

        for invalid_resource_name in invalid_resource_name_types:
            self.assertRaises(
                ValueError,
                limit.ProjectClaim,
                invalid_resource_name,
                project_id
            )

    def test_project_id_must_be_a_string(self):
        resource_name = uuid.uuid4().hex
        invalid_project_id_types = [
            True, False, [uuid.uuid4().hex], {'key': 'value'}, 1, 1.2
        ]

        for invalid_project_id in invalid_project_id_types:
            self.assertRaises(
                ValueError,
                limit.ProjectClaim,
                resource_name,
                invalid_project_id
            )

    def test_quantity_must_be_an_integer(self):
        resource_name = uuid.uuid4().hex
        project_id = uuid.uuid4().hex
        invalid_quantity_types = ['five', 5.5, [5], {5: 5}]

        for invalid_quantity in invalid_quantity_types:
            self.assertRaises(
                ValueError,
                limit.ProjectClaim,
                resource_name,
                invalid_quantity,
                quantity=invalid_quantity
            )
