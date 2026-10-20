"""Plan Layer — Query → Structured Plan → wait for the user.

`schemas` owns the Plan's bounds, `service` owns how a Plan is made and
stored, `graph` owns the ordering. Nothing else in the project may
validate a Plan.
"""
