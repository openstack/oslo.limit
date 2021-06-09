=======
Testing
=======

To test a project that uses oslo.limit, a fixture is provided. This
mocks out the connection to keystone and retrieval of registered and
project limits.

Example
=======

.. code-block:: python

   from oslo_limit import fixture

   class MyTest(unittest.TestCase):
       def setUp(self):
           super(MyTest, self).setUp()

           # Default limit of 10 widgets
           registered_limits = {'widgets': 10}

           # project2 gets 20 widgets
           project_limits = {'project2': {'widgets': 20}}

           self.useFixture(fixture.LimitFixture(registered_limits,
                                                project_limits))

       def test_thing(self):
           # ... use limit.Enforcer() as usual
