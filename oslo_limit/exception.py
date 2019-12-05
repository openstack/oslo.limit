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

from oslo_limit._i18n import _


class ProjectOverLimit(Exception):
    def __init__(self, project_id, over_limit_info_list):
        """Exception raised when a project goes over one or more limits

        :param project_id: the project id
        :param over_limit_info_list: list of OverLimitInfo objects
        """
        if not isinstance(over_limit_info_list, list):
            raise ValueError(over_limit_info_list)
        if len(over_limit_info_list) == 0:
            raise ValueError(over_limit_info_list)
        for info in over_limit_info_list:
            if not isinstance(info, OverLimitInfo):
                raise ValueError(over_limit_info_list)

        self.project_id = project_id
        self.over_limit_info_list = over_limit_info_list
        msg = _("Project %(project_id)s is over a limit for "
                "%(limits)s") % {'project_id': project_id,
                                 'limits': over_limit_info_list}
        super(ProjectOverLimit, self).__init__(msg)


class OverLimitInfo(object):
    def __init__(self, resource_name, limit, current_usage, delta):
        self.resource_name = resource_name
        self.limit = int(limit)
        self.current_usage = int(current_usage)
        self.delta = int(delta)

    def __str__(self):
        template = ("Resource %s is over limit of %s due to "
                    "current usage %s and delta %s")
        return template % (self.resource_name, self.limit,
                           self.current_usage, self.delta)

    def __repr__(self):
        return self.__str__()


class SessionInitError(Exception):
    def __init__(self, reason):
        msg = _(
            "Can't initialise OpenStackSDK session: %(reason)s."
        ) % {'reason': reason}
        super(SessionInitError, self).__init__(msg)
