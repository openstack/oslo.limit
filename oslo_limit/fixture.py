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

from collections.abc import Generator
from typing import Any
from unittest import mock

import fixtures as fixtures

from openstack.identity.v3 import endpoint as _endpoint
from openstack.identity.v3 import limit as _limit
from openstack.identity.v3 import region as _region
from openstack.identity.v3 import registered_limit as _registered_limit
from openstack.identity.v3 import service as _service
from openstack.test import fakes as sdk_fakes


def _fake_services(
    **query: dict[str, Any],
) -> Generator[_service.Service, None, None]:
    # we are the only ones calling this, so we know exactly what we should be
    # calling it with
    assert set(query) == {'type', 'name'}
    yield sdk_fakes.generate_fake_resource(
        _service.Service, type=query['type'], name=query['name']
    )


def _fake_region(
    region: str | _region.Region,
) -> _region.Region:
    if isinstance(region, str):
        region_id = region
    else:
        region_id = region.id

    return sdk_fakes.generate_fake_resource(_region.Region, id=region_id)


def _fake_endpoints(
    **query: dict[str, Any],
) -> Generator[_endpoint.Endpoint, None, None]:
    # we are the only ones calling this, so we know exactly what we should be
    # calling it with
    assert set(query) == {'service_id', 'region_id', 'interface'}
    yield sdk_fakes.generate_fake_resource(
        _endpoint.Endpoint,
        service_id=query['service_id'],
        region_id=query['region_id'],
        interface=query['interface'],
    )


class LimitFixture(fixtures.Fixture):
    def __init__(
        self,
        reglimits: dict[str, int],
        projlimits: dict[str, dict[str, int]],
    ) -> None:
        """A fixture for testing code that relies on Keystone Unified Limits.

        :param reglimits: A dictionary of {resource_name: limit} values to
                          simulate registered limits in keystone.
        :type reglimits: dict
        :param projlimits: A dictionary of dictionaries defining per-project
                           limits like {project_id: {resource_name: limit}}.
                           As in reality, only per-project overrides need be
                           provided here; any unmentioned projects or
                           resources will take the registered limit defaults.
        :type projlimits: dict
        """
        self.reglimits = reglimits
        self.projlimits = projlimits

    def get_reglimit_objects(
        self,
        service_id: str | None = None,
        region_id: str | None = None,
        resource_name: str | None = None,
    ) -> list[_registered_limit.RegisteredLimit]:
        registered_limits = []
        for name, value in self.reglimits.items():
            if resource_name and resource_name != name:
                continue

            registered_limit = sdk_fakes.generate_fake_resource(
                _registered_limit.RegisteredLimit,
                resource_name=name,
                default_limit=value,
            )
            registered_limits.append(registered_limit)

        return registered_limits

    def get_projlimit_objects(
        self,
        service_id: str | None = None,
        region_id: str | None = None,
        resource_name: str | None = None,
        project_id: str | None = None,
    ) -> list[_limit.Limit]:
        limits = []
        for proj_id, limit_dict in self.projlimits.items():
            if project_id and project_id != proj_id:
                continue

            for name, value in limit_dict.items():
                if resource_name and resource_name != name:
                    continue

                limit = sdk_fakes.generate_fake_resource(
                    _limit.Limit,
                    resource_name=name,
                    resource_limit=value,
                    project_id=proj_id,
                )
                limits.append(limit)

        return limits

    def setUp(self) -> None:
        super().setUp()

        # We mock our own cached connection to Keystone
        self.mock_conn = mock.MagicMock()
        self.useFixture(
            fixtures.MockPatch(
                'oslo_limit.limit._SDK_CONNECTION', new=self.mock_conn
            )
        )

        # Use a flat enforcement model
        mock_gem = self.useFixture(
            fixtures.MockPatch(
                'oslo_limit.limit.Enforcer._get_enforcement_model'
            )
        ).mock
        mock_gem.return_value = 'flat'

        # Fake keystone endpoint; this can be requested by ID or by name and we
        # need to handle both. First, requests by ID
        fake_endpoint = sdk_fakes.generate_fake_resource(
            _endpoint.Endpoint,
            service_id='service_id',
            region_id='region_id',
        )
        self.mock_conn.get_endpoint.return_value = fake_endpoint

        # Then, requests by name
        self.mock_conn.services.side_effect = _fake_services
        self.mock_conn.get_region.side_effect = _fake_region
        self.mock_conn.endpoints.side_effect = _fake_endpoints

        # Finally, fake the actual limits and registered limits calls
        self.mock_conn.limits.side_effect = self.get_projlimit_objects
        self.mock_conn.registered_limits.side_effect = (
            self.get_reglimit_objects
        )
