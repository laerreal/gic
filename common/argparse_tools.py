__all__ = [
    "composite_type"
]

from itertools import cycle

def composite_type(*arg_types):
    """ Defines checker for a composite argument (nargs=N). Given a checker per
value type of the composite argument, this function returns a
`composite_checker` that redirects each call to one of those value type
checkers. Current value type checker is chosen cyclically following the order
defined by `arg_types`. Each time an ArgumentParser is given such composite
argument the corresponding `composite_checker` is called N times (once per each
value of the composite argument). Each time a value is passed to consequent
value type checker by the `composite_checker`. After the last value the cycle
returned to the beginning and the `composite_checker` is ready to process next
composite argument.
    """

    def composite_checker(string, arg_types = cycle(arg_types)):
        current_type = next(arg_types)
        return current_type(string)

    return composite_checker
