from __future__ import absolute_import
from __future__ import print_function


import os
import sys
import tempfile
import hashlib
import subprocess

from shutil import copyfile
from .filetype import FileType
from .popenwrapper import Popen
from .arglistfilter import ArgumentListFilter

from .logconfig import logConfig

# Internal logger
_logger = logConfig(__name__)

def wcompile(mode):
    """ The workhorse, called from wllvm and wllvm++.
    """

    # Make sure we are not invoked from ccache
    parentCmd = subprocess.check_output(
            ['ps', '-o', 'comm=', '-p', str(os.getppid())], text=True)
    if parentCmd.strip() == 'ccache':
        # The following error message is invisible in terminal
        # when ccache is using its preprocessor mode
        _logger.error('Should not be invoked from ccache')
        # When ccache detects an error in the preprocessor mode,
        # it will fall back to running the real compiler (wllvm)
        sys.exit(-1)

    rc = 1

    legible_argstring = ' '.join(list(sys.argv)[1:])

    # for diffing with gclang
    _logger.info('Entering CC [%s]', legible_argstring)

    try:
        cmd = list(sys.argv)
        cmd = cmd[1:]

        builder = getBuilder(cmd, mode)

        af = builder.getBitcodeArglistFilter()

        rc = buildObject(builder)

        # phase one compile failed. no point continuing
        if rc != 0:
            _logger.error('Failed to compile using given arguments: [%s]', legible_argstring)
            return rc

        # no need to generate bitcode (e.g. configure only, assembly, ....)
        (skipit, reason) = af.skipBitcodeGeneration()
        if skipit:
            _logger.debug('No work to do: %s', reason)
            _logger.debug(af.__dict__)
            return rc

        # phase two
        buildAndAttachBitcode(builder, af)

    except Exception as e:
        _logger.warning('%s: exception case: %s', mode, str(e))

    _logger.debug('Calling %s returned %d', list(sys.argv), rc)
    return rc




fullSelfPath = os.path.realpath(__file__)
prefix = os.path.dirname(fullSelfPath)
driverDir = prefix
asDir = os.path.abspath(os.path.join(driverDir, 'dragonegg_as'))


# Environmental variable for path to compiler tools (clang/llvm-link etc..)
llvmCompilerPathEnv = 'LLVM_COMPILER_PATH'

RustcPathEnv ='RUSTC_PATH'

# Environmental variable for cross-compilation target.
binutilsTargetPrefixEnv = 'BINUTILS_TARGET_PREFIX'

# This is the ELF section name inserted into binaries
elfSectionName = '.llvm_bc'

# (Fix: 2016/02/16: __LLVM is now used by MacOS's ld so we changed the segment name to __WLLVM).
#
# These are the MACH_O segment and section name
# The SegmentName was __LLVM. Changed to __WLLVM to avoid clashing
# with a segment that ld now uses (since MacOS X 10.11.3?)
#
darwinSegmentName = '__WLLVM'
darwinSectionName = '__llvm_bc'


# Same as an ArgumentListFilter, but DO NOT change the name of the output filename when
# building the bitcode file so that we don't clobber the object file.
class ClangBitcodeArgumentListFilter(ArgumentListFilter):
    def __init__(self, arglist):
        localCallbacks = {'-o' : (1, ClangBitcodeArgumentListFilter.outputFileCallback)}
        #super(ClangBitcodeArgumentListFilter, self).__init__(arglist, exactMatches=localCallbacks)
        super().__init__(arglist, exactMatches=localCallbacks)

    def outputFileCallback(self, flag, filename):
        self.outputFilename = filename


def getHashedPathName(path):
    return hashlib.sha256(path.encode('utf-8')).hexdigest() if path else None


def attachBitcodePathToObject(bcPath, outFileName):
    # Don't try to attach a bitcode path to a binary.  Unfortunately
    # that won't work.
    (_, ext) = os.path.splitext(outFileName)
    _logger.debug('attachBitcodePathToObject: %s  ===> %s [ext = %s]', bcPath, outFileName, ext)

    #iam: just object files, right?
    fileType = FileType.getFileType(outFileName)
    if fileType not in (FileType.MACH_OBJECT, FileType.ELF_OBJECT):
    #if fileType not in (FileType.MACH_OBJECT, FileType.MACH_SHARED, FileType.ELF_OBJECT, FileType.ELF_SHARED):
        _logger.warning('Cannot attach bitcode path to "%s of type %s"', outFileName, FileType.getFileTypeString(fileType))
        return

    #iam: this also looks very dodgey; we need a more reliable way to do this:
    #if ext not in ('.o', '.lo', '.os', '.So', '.po'):
    #    _logger.warning('Cannot attach bitcode path to "%s of type %s"', outFileName, FileType.getReadableFileType(outFileName))
    #    return

    # Now just build a temporary text file with the full path to the
    # bitcode file that we'll write into the object file.
    f = tempfile.NamedTemporaryFile(mode='w+b', delete=False)
    absBcPath = os.path.abspath(bcPath)
    f.write(absBcPath.encode())
    f.write('\n'.encode())
    _logger.debug('Wrote "%s" to file "%s"', absBcPath, f.name)

    # Ensure buffers are flushed so that objcopy doesn't read an empty
    # file
    f.flush()
    os.fsync(f.fileno())
    f.close()

    binUtilsTargetPrefix = os.getenv(binutilsTargetPrefixEnv)

    # Now write our bitcode section
    if sys.platform.startswith('darwin'):
        objcopyBin = f'{binUtilsTargetPrefix}-{"ld"}' if binUtilsTargetPrefix else 'ld'
        objcopyCmd = [objcopyBin, '-r', '-keep_private_externs', outFileName, '-sectcreate', darwinSegmentName, darwinSectionName, f.name, '-o', outFileName]
    else:
        objcopyBin = f'{binUtilsTargetPrefix}-{"objcopy"}' if binUtilsTargetPrefix else 'objcopy'
        objcopyCmd = [objcopyBin, '--add-section', f'{elfSectionName}={f.name}', outFileName]
    orc = 0

    # loicg: If the environment variable WLLVM_BC_STORE is set, copy the bitcode
    # file to that location, using a hash of the original bitcode path as a name
    storeEnv = os.getenv('WLLVM_BC_STORE')
    if storeEnv:
        hashName = getHashedPathName(absBcPath)
        copyfile(absBcPath, os.path.join(storeEnv, hashName))

    try:
        if os.path.getsize(outFileName) > 0:
            objProc = Popen(objcopyCmd)
            orc = objProc.wait()
    except OSError:
        # configure loves to immediately delete things, causing issues for
        # us here.  Just ignore it
        os.remove(f.name)
        sys.exit(0)

    os.remove(f.name)

    if orc != 0:
        _logger.error('objcopy failed with %s', orc)
        sys.exit(-1)

class BuilderBase:
    def __init__(self, cmd, mode, prefixPath=None):
        self.af = None     #memoize the arglist filter
        self.cmd = cmd
        self.mode = mode

        # Used as prefix path for compiler
        if prefixPath:
            self.prefixPath = prefixPath
            # Ensure prefixPath has trailing slash
            if self.prefixPath[-1] != os.path.sep:
                self.prefixPath = self.prefixPath + os.path.sep
            # Check prefix path exists
            if not os.path.exists(self.prefixPath):
                errorMsg = 'Path to compiler "%s" does not exist'
                _logger.error(errorMsg, self.prefixPath)
                raise Exception(errorMsg)

        else:
            self.prefixPath = ''

    def getCommand(self):
        if self.af is not None:
            # need to remove things like "-dead_strip"
            forbidden = self.af.forbiddenArgs
            if forbidden:
                for baddy in forbidden:
                    self.cmd.remove(baddy)
        return self.cmd
    
    def getLLVM_ar(self):
        return [f'{self.prefixPath}{os.getenv("LLVM_AR_NAME") or "llvm-ar"}']

class ClangBuilder(BuilderBase):

    def getBitcodeGenerationFlags(self):
        # iam: If the environment variable LLVM_BITCODE_GENERATION_FLAGS is set we will add them to the
        # bitcode generation step
        bitcodeFLAGS  = os.getenv('LLVM_BITCODE_GENERATION_FLAGS')
        if bitcodeFLAGS:
            return bitcodeFLAGS.split()
        return []

    def getBitcodeCompiler(self):
        cc = self.getCompiler()
        return cc + ['-emit-llvm'] + self.getBitcodeGenerationFlags()

    def getCompiler(self):
        if self.mode == "wllvm++":
            env, prog = 'LLVM_CXX_NAME', 'clang++'
        elif self.mode == "wllvm":
            env, prog = 'LLVM_CC_NAME', 'clang'
        elif self.mode == "wfortran":
            env, prog = 'LLVM_F77_NAME', 'flang'
        else:
            raise Exception(f'Unknown mode {self.mode}')
        return [f'{self.prefixPath}{os.getenv(env) or prog}']

    def getBitcodeArglistFilter(self):
        if self.af is None:
            self.af = ClangBitcodeArgumentListFilter(self.cmd)
        return self.af

class DragoneggBuilder(BuilderBase):
    def getBitcodeCompiler(self):
        pth = os.getenv('LLVM_DRAGONEGG_PLUGIN')
        cc = self.getCompiler()
        # We use '-B' to tell gcc where to look for an assembler.
        # When we build LLVM bitcode we do not want to use the GNU assembler,
        # instead we want gcc to use our own assembler (see as.py).
        cmd = cc + ['-B', asDir, f'-fplugin={pth}', '-fplugin-arg-dragonegg-emit-ir']
        _logger.debug(cmd)
        return cmd

    def getCompiler(self):
        pfx = ''
        if os.getenv('LLVM_GCC_PREFIX') is not None:
            pfx = os.getenv('LLVM_GCC_PREFIX')

        if self.mode == "wllvm++":
            mode = 'g++'
        elif self.mode == "wllvm":
            mode = 'gcc'
        elif self.mode == "wfortran":
            mode = 'gfortran'
        else:
            raise Exception(f'Unknown mode {self.mode}')
        return [f'{self.prefixPath}{pfx}{mode}']

    def getBitcodeArglistFilter(self):
        if self.af is None:
            self.af = ArgumentListFilter(self.cmd)
        return self.af

class RustcBuilder(BuilderBase):
    def getBitcodeGenerationFlags(self):
        # iam: If the environment variable LLVM_BITCODE_GENERATION_FLAGS is set we will add them to the
        # bitcode generation step
        bitcodeFLAGS  = os.getenv('LLVM_BITCODE_GENERATION_FLAGS')
        if bitcodeFLAGS:
            return bitcodeFLAGS.split()
        return []
    def getBitcodeCompiler(self):
        rustc = self.getCompiler()
        return rustc + ['--emit=llvm-bc'] + self.getBitcodeGenerationFlags()
    def getCompiler(self):
        if self.mode == "wllvmrs":
            env,prog= 'LLVM_RUSTC_NAME', 'rustc'
        else:
            raise Exception(f'Unknown mode {self.mode}')
        return [f'{self.prefixPath}{os.getenv(env) or prog}']
    def getBitcodeArglistFilter(self):
        if self.af is None:
            self.af =ArgumentListFilter(self.cmd)
        return self.af

def getBuilder(cmd, mode):
    compilerEnv = 'LLVM_COMPILER'
    MixedCompilerEnv = "LLVM_MIXED_COMPILER"
    compiler = os.getenv(compilerEnv) # compiler clang/dragonegg
    if MixedCompilerEnv:
        othercompiler = os.getenv(MixedCompilerEnv) # Optional Rustc
    pathPrefix = os.getenv(llvmCompilerPathEnv) # Optional
    RustcPathPrefix = os.getenv(RustcPathEnv)
    # _logger.debug('WLLVM compiler using %s', cstring)
    if pathPrefix:
        _logger.debug('WLLVM compiler path prefix "%s"', pathPrefix)

    if  mode == 'wllvmrs' and othercompiler == 'rustc':
        _logger.debug('WLLVM compiler using %s', othercompiler)
        return RustcBuilder(cmd,mode,RustcPathPrefix)
    if compiler == 'clang':
        _logger.debug('WLLVM compiler using %s', compiler)
        return ClangBuilder(cmd, mode, pathPrefix)
    if compiler == 'dragonegg':
        _logger.debug('WLLVM compiler using %s', compiler)
        return DragoneggBuilder(cmd, mode, pathPrefix)
    
    if (compiler and othercompiler) is None:
        errorMsg = ' No compiler set. Please set environment variable %s'
        _logger.critical(errorMsg, compilerEnv)
        raise Exception(errorMsg)
    errorMsg = '%s = %s : Invalid compiler type'
    _logger.critical(errorMsg, compilerEnv, str(compiler))
    raise Exception(errorMsg)

def buildObject(builder):
    objCompiler = builder.getCompiler()
    objCompiler.extend(builder.getCommand())
    proc = Popen(objCompiler)
    rc = proc.wait()
    _logger.debug('buildObject rc = %d', rc)
    return rc

def ArObjectandAttachBitcode(builder):
    extracted_files = []
    objCompiler = builder.getCompiler()
    cc = builder.getLLVM_ar()  # 获取 `ar` 工具的路径
    af = builder.getBitcodeArglistFilter()
    outputarchive = af.getOutputFilename()
    
    # 构建命令，使用 grep 来过滤匹配的文件
    cc.extend(['t', outputarchive])  # 只需要这些命令来列出文件，后面的管道和 grep 会处理
    archiveMatchedfiles = subprocess.run(cc, capture_output=True, text=True)
    # _logger.debug('??!')
    if archiveMatchedfiles.returncode != 0:
        _logger.debug("Failed to list archive files of %s: %s",outputarchive,archiveMatchedfiles.stderr)
        return extracted_files
    matched_files = [line for line in archiveMatchedfiles.stdout.splitlines() if af.cratename in line]
    # 遍历匹配的文件
    for filename in matched_files:  # 处理标准输出，按行分割
        if af.cratename in filename:  # 假设你想通过某些标识过滤匹配的文件
            _logger.debug("Extracting %s from %s", filename, outputarchive)
            # 构建提取命令
            cc = builder.getLLVM_ar()
            cc.extend(['x', outputarchive, filename])
            # extract_cmd = [builder.getLLVM_ar(), "x", outputarchive, filename]
            # 执行提取命令
            # _logger.debug('??!')
            objects = subprocess.run(cc)
            # _logger.debug('??!')
            if objects.returncode == 0:  # 检查命令是否成功执行
                extracted_files.append(filename)  # 如果成功，添加到列表
            else:
                _logger.info("Failed to extract %s", filename)

    return extracted_files

# This command does not have the executable with it
def buildAndAttachBitcode(builder, af):

    #iam: when we have multiple input files we'll have to keep track of their object files.
    newObjectFiles = []

    hidden = not af.isCompileOnly

    if  len(af.inputFiles) == 1 and af.isCompileOnly:
        _logger.debug('Compile only case: %s', af.inputFiles[0])
        # iam:
        # we could have
        # "... -c -o foo.o" or even "... -c -o foo.So" which is OK, but we could also have
        # "... -c -o crazy-assed.objectfile" which we wouldn't get right (yet)
        # so we need to be careful with the objFile and bcFile
        # maybe python-magic is in our future ...
        srcFile = af.inputFiles[0]
        (objFile, bcFile) = af.getArtifactNames(srcFile, hidden)
        if af.outputFilename is not None:
            objFile = af.outputFilename
            bcFile = af.getBitcodeFileName()
        buildBitcodeFile(builder, srcFile, bcFile)
        attachBitcodePathToObject(bcFile, objFile)

    else:

        for srcFile in af.inputFiles:
            _logger.debug('Not compile only case: %s', srcFile)
            (objFile, bcFile) = af.getArtifactNames(srcFile, hidden)
            if srcFile.endswith('.rs'):
                extracted_files=ArObjectandAttachBitcode(builder)
                bcFile = af.outputBCname
                for obj in extracted_files:
                    _logger.debug('prepare to attach %s to %s',bcFile,obj)
                    attachBitcodePathToObject(bcFile,obj)
                    newObjectFiles.append(obj)
                break
            if hidden:
                _logger.debug('building %s by %s',objFile, srcFile)
                buildObjectFile(builder, srcFile, objFile)
                newObjectFiles.append(objFile)

            if srcFile.endswith('.bc'):
                _logger.debug('attaching %s to %s', srcFile, objFile)
                attachBitcodePathToObject(srcFile, objFile)
            else:
                _logger.debug('building and attaching %s to %s', bcFile, objFile)
                buildBitcodeFile(builder, srcFile, bcFile)
                attachBitcodePathToObject(bcFile, objFile)


    if not af.isCompileOnly:
        _logger.debug("link all files: %s",newObjectFiles)
        linkFiles(builder, newObjectFiles)

    sys.exit(0)

def linkFiles(builder, objectFiles):
    af = builder.getBitcodeArglistFilter()
    outputFile = af.getOutputFilename()
    if af.cratetype == 'staticlib':
        cc = builder.getLLVM_ar()
        cc.extend(['-rcs', outputFile])
        cc.extend(objectFiles)
        cc.extend(af.objectFiles)
        _logger.debug("link:%s",cc)
    else:
        cc = builder.getCompiler()
        cc.extend(objectFiles)
        cc.extend(af.objectFiles)
        cc.extend(af.linkArgs)
        cc.extend(['-o', outputFile])
    proc = Popen(cc)
    rc = proc.wait()
    if rc != 0:
        _logger.warning('Failed to link "%s"', str(cc))
        sys.exit(rc)


def buildBitcodeFile(builder, srcFile, bcFile):
    af = builder.getBitcodeArglistFilter()
    bcc = builder.getBitcodeCompiler()
    bcc.extend(af.compileArgs)
    if srcFile.endswith('.rs'):
        # for i, arg in enumerate(bcc):
        #     if arg.startswith('--emit='):
        #         bcc[i] = '--emit=llvm-bc'
        #         break
        #     if '--emit=llvm-bc' not in bcc:
        #         bcc.extend('--emit=llvm-bc')
        bcc.extend(['--emit=llvm-bc', srcFile])
    else:
        bcc.extend(['-c', srcFile])
    bcc.extend(['-o', bcFile])
    _logger.debug('buildBitcodeFile: %s', bcc)
    proc = Popen(bcc)
    rc = proc.wait()
    if rc != 0:
        _logger.warning('Failed to generate bitcode "%s" for "%s"', bcFile, srcFile)
        sys.exit(rc)

def buildObjectFile(builder, srcFile, objFile):
    af = builder.getBitcodeArglistFilter()
    cc = builder.getCompiler()
    cc.extend(af.compileArgs)
    cc.append(srcFile)
    if srcFile.endswith('.rs'):
            # for i, arg in enumerate(cc):
            # if arg.startswith('--emit='):
            #     cc[i] = '--emit=obj'
            #     break
            # if '--emit=obj' not in cc:
            #     cc.extend('--emit=obj')
        cc.extend(['--emit=obj', '-o', objFile])
    else:
        cc.extend(['-c', '-o', objFile])
    _logger.debug('buildObjectFile: %s', cc)
    proc = Popen(cc)
    rc = proc.wait()
    if rc != 0:
        _logger.warning('Failed to generate object "%s" for "%s"', objFile, srcFile)
        sys.exit(rc)

# bd & iam:
#
# case 1 (compileOnly):
#
# if the -c flag exists then so do all the .o files, and we need to
# locate them and produce and embed the bit code.
#
# locating them is easy:
#   either the .o is in the cmdline and we are in the simple case,
#   or else it was generated according to getObjectFilename
#
# we then produce and attach bitcode for each inputFile in the cmdline
#
#
# case 2 (compile and link)
#
#  af.inputFiles is not empty, and compileOnly is false.
#  in this case the .o's may not exist, we must regenerate
#  them in any case.
#
#
# case 3 (link only)
#
# in this case af.inputFiles is empty and we are done
#
#