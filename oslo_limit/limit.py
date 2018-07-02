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

import six


class ProjectClaim(object):

    def __init__(self, resource_name, project_id, quantity=None):
        """An object representing a claim of resources against a project.

        :param resource_name: A string representing the resource to claim.
        :type resource_name: string
        :param project_id: The ID of the project claiming the resources.
        :type project_id: string
        :param quantity: The number of resources being claimed.
        :type quantity: integer

        """

        if not isinstance(resource_name, six.string_types):
            msg = 'resource_name must be a string type.'
            raise ValueError(msg)

        if not isinstance(project_id, six.string_types):
            msg = 'project_id must be a string type.'
            raise ValueError(msg)

        if quantity and not isinstance(quantity, int):
            msg = 'quantity must be an integer.'
            raise ValueError(msg)

        self.resource_name = resource_name
        self.project_id = project_id
        self.quantity = quantity


class Enforcer(object):

    def __init__(self, claim, callback=None, verify=True):
        """Context manager for checking usage against resource claims.

        :param claim: An object containing information about the claim.
        :type claim: ``oslo_limit.limit.ProjectClaim``
        :param callback: A callable function that accepts a project_id string
                         as a parameter and calculates the current usage of a
                         resource.
        :type callable function:
        :param verify: Boolean denoting whether or not to verify the new usage
                       after executing a claim. This can be useful for handling
                       race conditions between clients claiming resources.
        :type verify: boolean

        """

        if not isinstance(claim, ProjectClaim):
            msg = 'claim must be an instance of oslo_limit.limit.ProjectClaim.'
            raise ValueError(msg)
        if callback and not callable(callback):
            msg = 'callback must be a callable function.'
            raise ValueError(msg)
        if verify and not isinstance(verify, bool):
            msg = 'verify must be a boolean value.'
            raise ValueError(msg)

        self.claim = claim
        self.callback = callback
        self.verify = verify

    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass
