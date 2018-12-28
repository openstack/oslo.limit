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

import copy

from keystoneauth1 import loading
from oslo_config import cfg

from oslo_limit._i18n import _

__all__ = [
    'list_opts',
    'register_opts',
]

CONF = cfg.CONF

endpoint_id = cfg.StrOpt(
    'endpoint_id',
    help=_("The service's endpoint id which is registered in Keystone."))

_options = [
    endpoint_id,
]

_option_group = 'oslo_limit'


def list_opts():
    """Return a list of oslo.config options available in the library.

    :returns: a list of (group_name, opts) tuples
    """

    return [(_option_group,
             copy.deepcopy(_options) +
             loading.get_session_conf_options() +
             loading.get_adapter_conf_options(include_deprecated=False)
             )]


def register_opts(conf):
    loading.register_session_conf_options(CONF, _option_group)
    loading.register_adapter_conf_options(CONF, _option_group,
                                          include_deprecated=False)
    conf.register_opts(_options, group=_option_group)
