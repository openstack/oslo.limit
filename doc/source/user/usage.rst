=======
 Usage
=======

To use oslo.limit in a project::

    from oslo_limit import limit


Conceptual Overview
===================

This library is meant to aid service developers performing usage checks for
resources managed by their service. It does this by clearly defining what is
being claimed, where resources are being claimed, and encapsulating enforcement
logic behind easy-to-use utilities. The following subsections introduce common
terms and concepts useful for communicating within the context of usage
enforcement for distributed systems.

Usage
-----

Usage is the real-time allocation of resources belonging to someone or
something. They are assumed to be present, or created, and thus accounted for.

With respect to OpenStack being a distributed system, the service responsible
for the resource is considered the usage authority for that resource. Ensuring
accurate usage almost always requires the service to perform a lookup and
possibly aggregate results to definitively provide usage information.

Limit
-----

A limit is the total number of resources someone or something *should* have.

With respect to OpenStack, the service which owns a particular resource may
also own that resource's limit. Conversely, limit information may be
centralized in a shared service. The latter is the pattern implied by the usage
of this library. The justification for decoupling resource limits from
individual services is to make it easier to provide a consistent experience for
users or operators setting and enforcing limits, regardless of the resource.

Claim
-----

A claim represents the quantity of resources being asked for by someone. Claims
are constrained by the relationship between resource usage and limits.
Successful claims are aggregated into usage.

Within the OpenStack ecosystem, claims can be made against specific targets
depending on the resource. For instance, a user may request two additional
servers for her project. This resulting claim might be two instances, the total
number of cores between both instances, the total memory consumed by both
instances, or all three. The claim is also targeted to a specific project,
which affects how this library asks for usage information.

Enforcement
-----------

Enforcement is the process of collecting usage data, limit information, and
claims in order to make a decision about whether a user should be able to
obtain more resources.

Adding oslo.limit to a service
==============================

Configuration
-------------

The oslo.limit library will by default lookup for a ``[oslo_limit]`` section
in the configuration file of the service. This section must contain
standard authentication information againt Keystone service in order to query
the unified limit APIs.

Be aware that the service account requires at a minimum a reader role assigned
on the system scope for enforcing limits, and authentication information
**should not** contains project information as keystoneauth library will
use it instead of system_scope.

In addition to the authentication information, ``oslo_limit``
configuration section must contain a way to identify the service in order to
filter limits by it. This can either be a combination of ``service_name``,
``service_type`` and ``region_name``, or simply ``endpoint_id``.

Here is an example of oslo_limit configuration

.. code-block:: ini

    [oslo_limit]
    auth_url = http://controller:5000
    auth_type = password
    user_domain_id = default
    username = MY_SERVICE
    system_scope = reader
    password = MY_PASSWORD
    service_name = my_service
    region_name = RegionOne

Create registered limit
-----------------------

Before enforcing a limit for a given resource, a registered limit **should**
exist for that resource. Registered limits can be, for example, configured
during service deployment.

.. note::
    Your user account must have the admin role assigned on the system scope to
    create registered limits.

Enforce a limit
---------------

Using enforcer consists mainly of defining a callback function for processing
the current usage of a given project, then calling the ``enforce`` function
with the amount of each resource you want to consume for a project, handling
the possible quota exceeded exceptions.

Here is a simple usage of limit enforcement

.. code-block:: python

    import logging

    from oslo_limit import limit
    from oslo_limit import exception as limit_exceptions

    # Callback function who need to return resource usage for each
    # resource asked in resources_names, for a given project_id
    def callback(project_id, resource_names):
        return {x: get_resource_usage_by_project(x, project_id) for x in resource_names}

    enforcer = limit.Enforcer(callback)
    try:
        # Check a limit for a given project for a set of resources, resource
        # unit are delta to be consumed
        enforcer.enforce('project_uuid', {'my_resource': 1})
    except limit_exceptions.ProjectOverLimit as e:
        # What to do in case of limit exception, e contain a list of
        # resource over quota
        logging.error(e)

Check a limit
-------------

Another usage pattern is to check a limit and usage for a given
project, outside the scope of enforcement. This may be useful in a
reporting API to be able to expose to a user the limit and usage
information that the enforcer would use to judge a resource
consumption event. Any limit passed to this API which is not
registered in keystone will be considered to be zero, in keeping with
the behavior of the enforcer assuming that "unregistered means no
quota."

.. note::
   This should ideally not be used to provide your own enforcement of
   limits, but rather for reporting or planning purposes.

Here is a simple usage of limit reporting

.. code-block:: python

    import logging

    from oslo_limit import limit

    # Callback function who need to return resource usage for each
    # resource asked in resources_names, for a given project_id
    def callback(project_id, resource_names):
        return {x: get_resource_usage_by_project(x, project_id) for x in resource_names}

    enforcer = limit.Enforcer(callback)
    usage = enforcer.calculate_usage('project_uuid', ['my_resource'])
    logging.info('%s using %i out of %i allowed %s resource' % (
        'project_uuid',
        usage['my_resource'].usage,
        usage['my_resource'].limit,
        'my_resource'))
