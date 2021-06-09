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

from oslotest import base

from oslo_limit import exception
from oslo_limit import fixture
from oslo_limit import limit


class TestFixture(base.BaseTestCase):
    def setUp(self):
        super(TestFixture, self).setUp()

        # Set up some default projects, registered limits,
        # and project limits
        reglimits = {'widgets': 100,
                     'sprockets': 50}
        projlimits = {
            'project2': {'widgets': 10},
        }
        self.useFixture(fixture.LimitFixture(reglimits, projlimits))

        # Some fake usage for projects
        self.usage = {
            'project1': {'sprockets': 10,
                         'widgets': 10},
            'project2': {'sprockets': 3,
                         'widgets': 3},
        }

        def proj_usage(project_id, resource_names):
            return self.usage[project_id]

        # An enforcer to play with
        self.enforcer = limit.Enforcer(proj_usage)

    def test_project_under_registered_limit_only(self):
        # Project1 has quota of 50 and 100 each, so no problem with
        # 10+1 usage.
        self.enforcer.enforce('project1', {'sprockets': 1,
                                           'widgets': 1})

    def test_project_over_registered_limit_only(self):
        # Project1 has quota of 100 widgets, usage of 112 is over
        # quota.
        self.assertRaises(exception.ProjectOverLimit,
                          self.enforcer.enforce,
                          'project1', {'sprockets': 1,
                                       'widgets': 102})

    def test_project_over_registered_limit(self):
        # delta=1 should be under the registered limit of 50
        self.enforcer.enforce('project2', {'sprockets': 1})

        # delta=50 should be over the registered limit of 50
        self.assertRaises(exception.ProjectOverLimit,
                          self.enforcer.enforce,
                          'project2', {'sprockets': 50})

    def test_project_over_project_limits(self):
        # delta=7 is usage=10, right at our project limit of 10
        self.enforcer.enforce('project2', {'widgets': 7})

        # delta=10 is usage 13, over our project limit of 10
        self.assertRaises(exception.ProjectOverLimit,
                          self.enforcer.enforce,
                          'project2', {'widgets': 10})

    def test_calculate_usage(self):
        # Make sure the usage calculator works with the fixture too
        u = self.enforcer.calculate_usage('project2', ['widgets'])['widgets']
        self.assertEqual(3, u.usage)
        self.assertEqual(10, u.limit)

        u = self.enforcer.calculate_usage('project1', ['widgets', 'sprockets'])
        self.assertEqual(10, u['sprockets'].usage)
        self.assertEqual(10, u['widgets'].usage)
        # Since project1 has no project limits, make sure we get the
        # registered limit values
        self.assertEqual(50, u['sprockets'].limit)
        self.assertEqual(100, u['widgets'].limit)
