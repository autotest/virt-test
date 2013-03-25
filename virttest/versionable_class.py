"""
VersionableClass provides class hierarchy which automatically select the right
version of a class. Class manipulation is used for this reason.
"""


class VersionableClass(object):
    """
    VersionableClass provides class hierarchy which automatically select right
    version of class. Class manipulation is used for this reason.
    By this reason is:
    Advantage) Only one version is working in one process. Class is changed in
               whole process.
    Disadvantage) Only one version is working in one process.

    Example of usage (in base_utils_unittest):

    class FooC(object):
        pass

    #Not implemented get_version -> not used for versioning.
    class VCP(FooC, VersionableClass):
        def __new__(cls, *args, **kargs):
            VCP.master_class = VCP
            return super(VCP, cls).__new__(cls, *args, **kargs)

        def foo(self):
            pass

    class VC2(VCP, VersionableClass):
        @staticmethod
        def get_version():
            return "get_version_from_system"

        @classmethod
        def is_right_version(cls, version):
            if version is not None:
                if "version is satisfied":
                    return True
            return False

        def func1(self):
            print "func1"

        def func2(self):
            print "func2"

    # get_version could be inherited.
    class VC3(VC2, VersionableClass):
        @classmethod
        def is_right_version(cls, version):
            if version is not None:
                if "version+1 is satisfied":
                    return True
            return False

        def func2(self):
            print "func2_2"

    class M(VCP):
        pass

    m = M()   # <- When class is constructed the right version is
              #    automatically selected. In this case VC3 is selected.
    m.func2() # call VC3.func2(m)
    m.func1() # call VC2.func1(m)
    m.foo()   # call VC1.foo(m)

    # When controlled "program" version is changed then is necessary call
     check_repair_versions or recreate object.

    m.check_repair_versions()

    # priority of class. (change place where is method searched first in group
    # of verisonable class.)

    class PP(VersionableClass):
        def __new__(cls, *args, **kargs):
            PP.master_class = PP
            return super(PP, cls).__new__(cls, *args, **kargs)

    class PP2(PP, VersionableClass):
        @staticmethod
        def get_version():
            return "get_version_from_system"

        @classmethod
        def is_right_version(cls, version):
            if version is not None:
                if "version is satisfied":
                    return True
            return False

        def func1(self):
            print "PP func1"

    class N(VCP, PP):
        pass

    n = N()

    n.func1() # -> "func2"

    n.set_priority_class(PP, [VCP, PP])

    n.func1() # -> "PP func1"

    Necessary for using:
    1) Subclass of versionable class must have implemented class methods
      get_version and is_right_version. These two methods are necessary
      for correct version section. Class without this method will be never
      chosen like suitable class.

    2) Every class derived from master_class have to add to class definition
      inheritance from VersionableClass. Direct inheritance from Versionable
      Class is use like a mark for manipulation with VersionableClass.

    3) Master of VersionableClass have to defined class variable
      cls.master_class.
    """
    def __new__(cls, *args, **kargs):
        cls.check_repair_versions()
        return super(VersionableClass, cls).__new__(cls, *args, **kargs)

    #VersionableClass class management class.

    @classmethod
    def check_repair_versions(cls, master_classes=None):
        """
        Check version of versionable class and if version not
        match repair version to correct version.

        @param master_classes: Check and repair only master_class.
        @type master_classes: list.
        """
        if master_classes is None:
            master_classes = cls._find_versionable_baseclass()
        for base in master_classes:
            cls._check_repair_version_class(base)


    @classmethod
    def set_priority_class(cls, prioritized_class, group_classes):
        """
        Set class priority. Limited only for change bases class priority inside
        one subclass.__bases__ after that continue to another class.
        """
        def change_position(ccls):
            if not VersionableClass in ccls.__bases__:
                bases = list(ccls.__bases__)

                index = None
                remove_variant = None
                for i, item in enumerate(ccls.__bases__):
                    if (VersionableClass in item.__bases__ and
                        item.master_class in group_classes):
                        if index is None:
                            index = i
                        if item.master_class is prioritized_class:
                            remove_variant = item
                            bases.remove(item)
                            break
                else:
                    return

                bases.insert(index, remove_variant)
                ccls.__bases__ = tuple(bases)

        def find_cls(ccls):
            change_position(ccls)
            for base in ccls.__bases__:
                find_cls(base)

        find_cls(cls)


    @classmethod
    def _check_repair_version_class(cls, master_class):
        version = None
        for class_version in master_class._find_versionable_subclass():
            try:
                version = class_version.get_version()
                if class_version.is_right_version(version):
                    cls._switch_by_class(class_version)
                    break
            except NotImplementedError:
                continue
        else:
            cls._switch_by_class(class_version)


    @classmethod
    def _find_versionable_baseclass(cls):
        """
        Find versionable class in master class.
        """
        ver_class = []
        for superclass in cls.mro():
            if VersionableClass in superclass.__bases__:
                ver_class.append(superclass.master_class)

        return set(ver_class)


    @classmethod
    def _find_versionable_subclass(cls):
        """
        Find versionable subclasses which subclass.master_class == cls
        """
        subclasses = [cls]
        for sub in cls.__subclasses__():
            if VersionableClass in list(sub.__bases__):
                subclasses.extend(sub._find_versionable_subclass())
        return subclasses


    @classmethod
    def _switch_by_class(cls, new_class):
        """
        Finds all class with same master_class as new_class in class tree
        and replaces them by new_class.

        @param new_class: Class for replacing.
        """
        def find_replace_class(bases):
            for base in bases:
                if (VersionableClass in base.__bases__ and
                    base.master_class == new_class.master_class):
                    bnew = list(bases)
                    bnew[bnew.index(base)] = new_class
                    return tuple(bnew)
                else:
                    bnew = find_replace_class(base.__bases__)
                    if bnew:
                        base.__bases__ = bnew

        bnew = find_replace_class(cls.__bases__)
        if bnew:
            cls.__bases__ = bnew


    # Method defined in part below must be defined in
    # verisonable class subclass.

    @classmethod
    def get_version(cls):
        """
        Get version of installed OpenVSwtich.
        Must be re-implemented for in child class.

        @return: Version or None when get_version is unsuccessful.
        """
        raise NotImplementedError("Method 'get_verison' must be"
                                  " implemented in child class")


    @classmethod
    def is_right_version(cls, version):
        """
        Check condition for select control class.
        Function must be re-implemented in new OpenVSwitchControl class.
        Must be re-implemented for in child class.

        @param version: version of OpenVSwtich
        """
        raise NotImplementedError("Method 'is_right_version' must be"
                                  " implemented in child class")
