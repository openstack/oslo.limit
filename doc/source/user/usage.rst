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
