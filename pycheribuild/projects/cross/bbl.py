#
# Copyright (c) 2018 James Clarke
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#

from .crosscompileproject import CompilationTargets, CrossCompileAutotoolsProject
from ..build_qemu import BuildQEMU
from ..project import (BuildType, CheriConfig, ComputedDefaultValue, CrossCompileTarget, DefaultInstallDir,
                       GitRepository, MakeCommandKind, Project)


class BuildBBLBase(CrossCompileAutotoolsProject):
    doNotAddToTargets = True
    repository = GitRepository("https://github.com/CTSRD-CHERI/riscv-pk",
        force_branch=True, default_branch="cheri_purecap",  # Compilation fixes for clang and support for CHERI
        old_urls=[b"https://github.com/jrtc27/riscv-pk.git"])
    make_kind = MakeCommandKind.GnuMake
    _always_add_suffixed_targets = True
    is_sdk_target = False
    needs_sysroot = False  # Should be buildable without a sysroot
    kernel_class = None
    cross_install_dir = DefaultInstallDir.ROOTFS
    without_payload = False
    mem_start = "0x80000000"

    @classmethod
    def dependencies(cls, config: CheriConfig):
        result = super().dependencies(config)
        if cls.kernel_class:
            xtarget = cls.get_crosscompile_target(config)
            result.append(cls.kernel_class.get_class_for_target(xtarget).target)
        return result

    def setup(self):
        self.COMMON_LDFLAGS.extend(["-nostartfiles", "-nostdlib", "-static"])
        self.CFLAGS.extend(["-nostartfiles", "-nostdlib", "-static", "-ffreestanding"])
        self.COMMON_FLAGS.append("-nostdlib")
        super().setup()
        self.common_warning_flags.append("-Werror=undef")
        self.common_warning_flags.append("-Werror=return-type")
        self.common_warning_flags.append("-Wall")

        if self.crosscompile_target.is_hybrid_or_purecap_cheri():
            # We have to build a purecap if we want to support CHERI
            self.configureArgs.append("--with-abi=l64pc128")
            # Enable CHERI extensions
            self.configureArgs.append("--with-arch=rv64imafdcxcheri")
            self.configureArgs.append("--with-mem-start=" + self.mem_start)
        else:
            self.configureArgs.append("--with-abi=lp64")
            self.configureArgs.append("--with-arch=rv64imafdc")

        if self.build_type == BuildType.DEBUG:
            self.configureArgs.append("--enable-logo")  # For debugging

        self.configureArgs.append("--disable-fp-emulation")  # Should not be needed

        # BBL build uses weird objcopy flags and therefore requires GNU objcopy if you want to build everything
        # Fortunetaly we don't need this when building only BBL.
        self.add_configure_and_make_env_arg("OBJCOPY", self.sdk_bindir / "llvm-objcopy")
        self.add_configure_and_make_env_arg("READELF", self.sdk_bindir / "llvm-readelf")
        self.add_configure_and_make_env_arg("RANLIB", self.sdk_bindir / "llvm-ranlib")
        self.add_configure_and_make_env_arg("AR", self.sdk_bindir / "llvm-ar")

        if self.without_payload:
            # Build an OpenSBI fw_jump style BBL
            assert self.kernel_class is None
            self.configureArgs.append("--without-payload")
        else:
            # Add the kernel as a payload:
            assert self.kernel_class is not None
            kernel_path = self.kernel_class.get_installed_kernel_path(self, cross_target=self.crosscompile_target)
            self.configureArgs.append("--with-payload=" + str(kernel_path))

    def compile(self, **kwargs):
        self.run_make("bbl")

    def install(self, **kwargs):
        self.installFile(self.buildDir / "bbl", self.real_install_root_dir / "bbl")

    @classmethod
    def get_installed_kernel_path(cls, caller, config: CheriConfig = None, cross_target: CrossCompileTarget = None):
        return cls.get_instance(caller, config=config, cross_target=cross_target).real_install_root_dir / "bbl"


def _bbl_install_dir(config: CheriConfig, project: Project):
    dir_name = project.crosscompile_target.generic_suffix.replace("baremetal-", "")
    return config.cheri_sdk_dir / ("bbl" + project.build_dir_suffix) / dir_name


# Build BBL without an embedded payload
class BuildBBLNoPayload(BuildBBLBase):
    target = "bbl"
    project_name = "bbl"
    without_payload = True
    cross_install_dir = DefaultInstallDir.CUSTOM_INSTALL_DIR
    supported_architectures = [CompilationTargets.BAREMETAL_NEWLIB_RISCV64_PURECAP,
                               CompilationTargets.BAREMETAL_NEWLIB_RISCV64]

    _default_install_dir_fn = ComputedDefaultValue(function=_bbl_install_dir,
        as_string="$SDK_ROOT/bbl/riscv{32,64}{,-purecap}")

    def install(self):
        super().install()
        # Only install BuildBBLNoPayload as the QEMU bios and not the GFE version by checking build_dir_suffix
        if self.crosscompile_target.is_cheri_purecap() and not self.build_dir_suffix:
            # Install into the QEMU firware directory so that `-bios default` works
            qemu_fw_dir = BuildQEMU.getInstallDir(self, cross_target=CompilationTargets.NATIVE) / "share/qemu/"
            self.makedirs(qemu_fw_dir)
            self.run_cmd(self.sdk_bindir / "llvm-objcopy", "-S", "-O", "binary",
                self.get_installed_kernel_path(self), qemu_fw_dir / "bbl-riscv64cheri-virt-fw_jump.bin")


class BuildBBLNoPayloadGFE(BuildBBLNoPayload):
    mem_start = "0xc0000000"
    target = "bbl-gfe"
    project_name = "bbl"  # reuse same source dir
    build_dir_suffix = "-gfe"  # but not the build dir

    _default_install_dir_fn = ComputedDefaultValue(function=_bbl_install_dir,
        as_string="$SDK_ROOT/bbl-gfe/riscv{32,64}{,-purecap}")


class BuildBBLNoPayloadFETT(BuildBBLNoPayloadGFE):
    target = "bbl-fett"
    build_dir_suffix = "-fett"  # but not the build dir

    _default_install_dir_fn = ComputedDefaultValue(
        function=lambda config, project: config.cheri_sdk_dir / "bbl-fett" / project.crosscompile_target.generic_suffix,
        as_string="$SDK_ROOT/bbl-fett/riscv{32,64}{c,-hybrid}")


# class BuildBBLFreeBSDRISCV(BuildBBLBase):
#     project_name = "bbl"  # reuse same source dir
#     target = "bbl-freebsd"
#     build_dir_suffix = "freebsd"
#     supported_architectures = [CompilationTargets.FREEBSD_RISCV]
#     kernel_class = BuildFreeBSD
#
#
# class BuildBBLFreeBSDWithDefaultOptionsRISCV(BuildBBLBase):
#     project_name = "bbl"  # reuse same source dir
#     target = "bbl-freebsd-with-default-options"
#     build_dir_suffix = "freebsd-with-default-options"
#     supported_architectures = [CompilationTargets.FREEBSD_RISCV]
#     kernel_class = BuildFreeBSDWithDefaultOptions
#
#
# class BuildBBLCheriBSDRISCV(BuildBBLBase):
#     project_name = "bbl"  # reuse same source dir
#     target = "bbl-cheribsd"
#     build_dir_suffix = "cheribsd"
#     supported_architectures = [CompilationTargets.CHERIBSD_RISCV_HYBRID, CompilationTargets.CHERIBSD_RISCV_NO_CHERI]
#     kernel_class = BuildCHERIBSD
