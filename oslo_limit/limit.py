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


class Enforcer(object):

    def __init__(self, deltas, callback=None, verify=True):
        """An object for checking usage against resource limits and requests.

        :param deltas: An dictionary containing resource names as keys and
                       requests resource quantities as values.
        :type deltas: dictionary
        :param callback: A callable function that accepts a project_id string
                         as a parameter and calculates the current usage of a
                         resource.
        :type callable function:
        :param verify: Boolean denoting whether or not to verify the new usage
                       after checking the resource delta. This can be useful
                       for handling race conditions between clients claiming
                       resources.
        :type verify: boolean

        """

        if not isinstance(deltas, dict):
            msg = 'deltas must be a dictionary.'
            raise ValueError(msg)
        if callback and not callable(callback):
            msg = 'callback must be a callable function.'
            raise ValueError(msg)
        if verify and not isinstance(verify, bool):
            msg = 'verify must be a boolean value.'
            raise ValueError(msg)

        self.deltas = deltas
        self.callback = callback
        self.verify = verify

    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass
