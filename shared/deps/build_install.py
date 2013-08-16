#!/usr/bin/python

'''
Script to build and install packages from git in VMs
'''

import os, sys
import optparse
import subprocess

git_repo = {}
configure_options = {}
autogen_options = {}
prefix_defaults = {}

# Git repo associated with each packages 
git_repo["spice-protocol"] = "git://git.freedesktop.org/git/spice/spice-protocol"
git_repo["spice-gtk"] = "git://anongit.freedesktop.org/spice/spice-gtk"
git_repo["spice-vd-agent"] = "git://git.freedesktop.org/git/spice/linux/vd_agent"
git_repo["xf86-video-qxl"] = "git://anongit.freedesktop.org/xorg/driver/xf86-video-qxl"

# options to pass
autogen_options["spice-gtk"] = "--with-gtk=2.0 --disable-gtk-doc --disable-introspection"
autogen_options["xf86-video-qxl"] = "--libdir=\"/usr/lib64\""
prefix_defaults["spice-protocol"] = "/usr/local"
prefix_defaults["spice-vd-agent"] = "/usr/local"


usageMsg = "\nUsage: %prog -p package-to-build [options]\n\n"
usageMsg += "build_install.py lets you build any package from a git repo.\n"
usageMsg += "It downloads the git repo, builds and installs it.\n"
usageMsg += "You can pass options such as git repo, branch you want to build at,\n"
usageMsg += "specific commit to build at, build options to pass to autogen.sh\n"
usageMsg += "and which location to install the built binaries to.\n\n"
usageMsg += "The following aliases for SPICE are already set: "
usageMsg += "\n\tspice-protocol\t ->\t SPICE protocol "
usageMsg += "\n\tspice-gtk\t ->\t SPICE GTK "
usageMsg += "\n\tspice-vd-agent\t ->\t SPICE VD-Agent "
usageMsg += "\n\txf86-video-qxl\t ->\t QXL device driver"

# Getting all parameters
parser = optparse.OptionParser(usage=usageMsg)
parser.add_option("-p", "--package", dest="pkgName",
                 help="Name of package to build. Required.")
parser.add_option("-g", "--gitRepo", dest="gitRepo",
                 help="Repo to download and build package from")
parser.add_option("-b", "--branch", dest="branch", default="master",
                 help="Branch to checkout and use")
parser.add_option("-d", "--destDir", dest="destDir",
                 help="Destination Dir to store repo at")
parser.add_option("-c", "--commit", dest="commit",
                 help="Specific commit to download")
parser.add_option("-l","--prefix", dest="prefix",
                 help="Location to store built binaries/libraries")
parser.add_option("-o","--buildOptions", dest="buildOptions",
                 help="Options to pass to autogen.sh while building")
                 

(options, args) = parser.parse_args()

if not options.pkgName:
   print "Missing required arguments"
   parser.print_help()
   sys.exit(1)

pkgName = options.pkgName
branch = options.branch
destDir = options.destDir
commit = options.commit
prefix = options.prefix
if options.buildOptions:
   autogen_options[pkgName] = options.buildOptions
if options.gitRepo:
   git_repo[pkgName] = options.gitRepo

ret = os.system("which git")
if ret != 0:
   print "Missing git command!"
   sys.exit(1)

# Create destination directory
if destDir is None:
   basename = git_repo[pkgName].split("/")[-1]
   destDir = os.path.join("/tmp", basename)

# If destination directory doesn't exist, create it
if not os.path.exists(destDir):
   print "Creating directory %s for git repo %s" % (destDir, git_repo[pkgName])
   os.makedirs(destDir)

# Switch to the directory
os.chdir(destDir)

# If git repo already exists, reset. If not, initialize
if os.path.exists('.git'):
   print "Resetting previously existing git repo at %s for receiving git repo %s" % (destDir, git_repo[pkgName])
   subprocess.check_call("git reset --hard".split())
else:
   print "Initializing new git repo at %s for receiving git repo %s" % (destDir, git_repo[pkgName])
   subprocess.check_call("git init".split())

# Fetch the contents of the repo
print "Fetching git [REP '%s' BRANCH '%s'] -> %s" % (git_repo[pkgName], branch, destDir)
subprocess.check_call(("git fetch -q -f -u -t %s %s:%s" % (git_repo[pkgName], branch, branch)).split())

# checkout the branch specified, master by default
print "Checking out branch %s" % branch
subprocess.check_call(("git checkout %s" % branch).split())

# If a certain commit is specified, checkout that commit
if commit is not None:
   print "Checking out commit %s" % commit
   subprocess.check_call(("git checkout %s" % commit).split())
else:
   print "Specific commit not specified"


# Adding remote origin
print "Adding remote origin"
args = ("git remote add origin %s" % git_repo[pkgName]).split()
output = subprocess.Popen(args, shell=False,
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      close_fds=True).stdout.read().strip()

# Get the commit and tag which repo is at
args = 'git log --pretty=format:%H -1'.split()
print "Running 'git log --pretty=format:%H -1' to get top commit"
top_commit = subprocess.Popen(args, shell=False,
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      close_fds=True).stdout.read().strip()

args = 'git describe'.split()
print "Running 'git describe' to get top tag"
top_tag = subprocess.Popen(args, shell=False,
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      close_fds=True).stdout.read().strip()
if top_tag is None:
   top_tag_desc = 'no tag found'
else:
   top_tag_desc = 'tag %s' % top_tag
print "git commit ID is %s (%s)" % (top_commit, top_tag_desc)


# If prefix to be passed to autogen.sh is in the defaults, use that
if pkgName in prefix_defaults.keys() and options.prefix is None:
   prefix = prefix_defaults[pkgName]

# if no prefix is set, the use default PKG_CONFIG_PATH. If not, set to prefix's PKG_CONFIG_PATH 
if prefix is None:
   env_vars = "PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/usr/local/share/pkgconfig:/usr/local/lib:"
else:
   env_vars = "PKG_CONFIG_PATH=$PKG_CONFIG_PATH:%s/share/pkgconfig:%s/lib:" % (prefix, 
                                                                               prefix)


# Running autogen.sh with prefix and any other options
# Using os.system because subprocess.Popen would not work 
# with autogen.sh properly. --prefix would not get set 
# properly with it

cmd = destDir + "/autogen.sh"
if prefix is not None:
   cmd += " --prefix=\"" + prefix + "\""
if pkgName in autogen_options.keys():
   cmd += " " + autogen_options[pkgName]

print "Running '%s %s'" % (env_vars, cmd)
ret = os.system(env_vars + " " + cmd)
if ret != 0:
   print "Autogen.sh failed! Exiting!"
   sys.exit(ret)


# Running 'make' to build and using os.system again
cmd = "make"
print "Running '%s %s'" % (env_vars, cmd)
ret = os.system("%s %s" % (env_vars, cmd))
if ret != 0:
   print "make failed! Exiting!"
   sys.exit(ret)

# Running 'make install' to install the built libraries/binaries
cmd = "make install"
print "Running '%s %s'" % (env_vars, cmd)
ret = os.system("%s %s" % (env_vars, cmd))
if ret != 0:
   print "make install failed! Exiting!"
   sys.exit(ret)
