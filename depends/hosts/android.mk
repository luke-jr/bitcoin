# Android NDK r28c, arm64-v8a, targeting API 28 by default.
ANDROID_API ?= 28
ANDROID_ABI = arm64-v8a
ANDROID_NDK ?= $(SDK_PATH)/android-ndk-r28c
ANDROID_NDK := $(abspath $(ANDROID_NDK))

ifneq ($(host_arch),aarch64)
$(error Android depends currently supports HOST=aarch64-linux-android)
endif

android_toolchain = $(ANDROID_NDK)/toolchains/llvm/prebuilt/$(build_os)-$(build_arch)
android_CC = $(android_toolchain)/bin/aarch64-linux-android$(ANDROID_API)-clang
android_CXX = $(android_toolchain)/bin/aarch64-linux-android$(ANDROID_API)-clang++
android_AR = $(android_toolchain)/bin/llvm-ar
android_RANLIB = $(android_toolchain)/bin/llvm-ranlib
android_NM = $(android_toolchain)/bin/llvm-nm
android_STRIP = $(android_toolchain)/bin/llvm-strip
android_OBJCOPY = $(android_toolchain)/bin/llvm-objcopy
android_OBJDUMP = $(android_toolchain)/bin/llvm-objdump

android_CFLAGS = -pipe -std=$(C_STANDARD) -fPIC
android_CXXFLAGS = -pipe -std=$(CXX_STANDARD) -fPIC
android_release_CFLAGS = -O2
android_release_CXXFLAGS = $(android_release_CFLAGS)
android_debug_CFLAGS = -O1 -g
android_debug_CXXFLAGS = $(android_debug_CFLAGS)

android_cmake_system_name = Android
android_cmake_system_version = $(ANDROID_API)
android_cmake_opts = -DCMAKE_ANDROID_NDK=$(ANDROID_NDK) -DCMAKE_SYSTEM_VERSION=$(ANDROID_API)
android_cmake_opts += -DCMAKE_ANDROID_ARCH_ABI=$(ANDROID_ABI) -DCMAKE_ANDROID_STL_TYPE=c++_static -DTHREADS_PREFER_PTHREAD_FLAG=ON
