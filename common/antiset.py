__all__ = [
    "antiset"
]

class antiset(object):
    """ Anti-set contains anything you ask except for explicitly removed
    items. """

    __slots__ = ["__removed"]

    def __init__(self):
        self.__removed = set()

    def remove(self, item):
        # remember explicitly removed items
        self.__removed.add(item)

    def __contains__(self, item):
        # If an item was not explicitly removed then it is in this set.
        return item not in self.__removed

    def __nonzero__(self):
        # You cannot remove anything in the world! Hence, anti-set is always
        # has something.
        return True

    def __iter__(self):
        raise TypeError("You cannot iterate all in the world!")

if __name__ == "__main__":
    s = antiset()
    if s and "i" in s:
        s.remove("i")
        print("i" in s)
        for i in s:
            print(i)
