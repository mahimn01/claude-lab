"""macOS Keychain access without putting credentials in a subprocess argv."""

import ctypes as C
import sys


class CredentialError(RuntimeError):
    pass


class Keychain:
    def __init__(self, service="local.claude-lab.oauth.v1"):
        if sys.platform != "darwin":
            raise CredentialError("This version requires macOS Keychain.")
        self.service = service.encode()
        self.sec = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ptr, uint = C.c_void_p, C.c_uint32
        self.sec.SecKeychainFindGenericPassword.argtypes = [
            ptr, uint, C.c_char_p, uint, C.c_char_p,
            C.POINTER(uint), C.POINTER(ptr), C.POINTER(ptr),
        ]
        self.sec.SecKeychainAddGenericPassword.argtypes = [
            ptr, uint, C.c_char_p, uint, C.c_char_p, uint, ptr, C.POINTER(ptr),
        ]
        self.sec.SecKeychainItemModifyAttributesAndData.argtypes = [ptr, ptr, uint, ptr]
        self.sec.SecKeychainItemDelete.argtypes = [ptr]
        self.sec.SecKeychainItemFreeContent.argtypes = [ptr, ptr]
        for name in ("SecKeychainFindGenericPassword", "SecKeychainAddGenericPassword",
                     "SecKeychainItemModifyAttributesAndData", "SecKeychainItemDelete",
                     "SecKeychainItemFreeContent"):
            getattr(self.sec, name).restype = C.c_int32
        self.cf.CFRelease.argtypes = [ptr]
        self.cf.CFRelease.restype = None

    @staticmethod
    def _check(status):
        if status:
            raise CredentialError(
                f"Keychain returned OSStatus {status}. Unlock the login keychain "
                "and allow this Python executable access if macOS asks."
            )

    def _find(self, name):
        account = name.encode()
        size, data, item = C.c_uint32(), C.c_void_p(), C.c_void_p()
        status = self.sec.SecKeychainFindGenericPassword(
            None, len(self.service), self.service, len(account), account,
            C.byref(size), C.byref(data), C.byref(item),
        )
        if status == -25300:  # errSecItemNotFound
            return None, None
        self._check(status)
        try:
            value = C.string_at(data, size.value).decode()
        finally:
            self.sec.SecKeychainItemFreeContent(None, data)
        return value, item

    def get(self, name):
        value, item = self._find(name)
        if item:
            self.cf.CFRelease(item)
        if value is None:
            raise CredentialError(f"No token in Keychain for {name!r}; run add again.")
        return value

    def put(self, name, value):
        _, item = self._find(name)
        payload, account = value.encode(), name.encode()
        try:
            if item:
                status = self.sec.SecKeychainItemModifyAttributesAndData(
                    item, None, len(payload), payload,
                )
            else:
                status = self.sec.SecKeychainAddGenericPassword(
                    None, len(self.service), self.service, len(account), account,
                    len(payload), payload, None,
                )
            self._check(status)
        finally:
            if item:
                self.cf.CFRelease(item)

    def delete(self, name):
        _, item = self._find(name)
        if item:
            try:
                self._check(self.sec.SecKeychainItemDelete(item))
            finally:
                self.cf.CFRelease(item)
