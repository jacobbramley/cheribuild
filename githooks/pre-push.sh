#!/bin/sh

# An example hook script to verify what is about to be pushed.  Called by "git
# push" after it has checked the remote status, but before anything has been
# pushed.  If this script exits with a non-zero status nothing will be pushed.
#
# This hook is called with the following parameters:
#
# $1 -- Name of the remote to which the push is being done
# $2 -- URL to which the push is being done
#
# If pushing without using a named remote those arguments will be equal.
#
# Information about the commits which are being pushed is supplied as lines to
# the standard input in the form:
#
#   <local ref> <local sha1> <remote ref> <remote sha1>
#
# This sample shows how to prevent push of commits where the log message starts
# with "WIP" (work in progress).

remote="$1"
url="$2"

z40=0000000000000000000000000000000000000000

while read local_ref local_sha remote_ref remote_sha
do
	if [ "$local_sha" = $z40 ]
	then
		# Handle delete
		:
	else
		if [ "$remote_sha" = $z40 ]
		then
			# New branch, examine all commits
			range="$local_sha"
		else
			# Update to existing branch, examine new commits
			range="$remote_sha..$local_sha"
		fi
		# check that there are no obvious mistakes:
		if ! ./cheribuild.py -p __run_everything__ --clean 2>/dev/null >/dev/null; then
			echo "Failed to run ./cheribuild.py -p __run_everything__, don't push this!"
			exit 1
		fi
		./cheribuild.py --help > /dev/null
		WORKSPACE=/tmp CPU=mips ./jenkins-cheri-build.py --tarball -p llvm >/dev/null
		if ! env WORKSPACE=/tmp CPU=mips ./jenkins-cheri-build.py --build -p llvm 2>/dev/null >/dev/null; then
			echo "Failed to run ./jenkins-cheri-build.py, don't push this!"
			exit 1
		fi

		# Run python tests before pushing
		if [ -e pytest.ini ]; then
			python3 -m pytest -q . >&2 || exit 1
		fi

		# Check for WIP commit
		commit=`git rev-list -n 1 --grep '^WIP' "$range"`
		if [ -n "$commit" ]
		then
			echo >&2 "Found WIP commit in $local_ref, not pushing"
			exit 1
		fi
		# Check for rebase commit
		commit=`git rev-list -n 1 --grep '^rebase' "$range"`
		if [ -n "$commit" ]
		then
			echo >&2 "Found rebase commit $commit in $local_ref, not pushing"
			exit 1
		fi
	fi
done

exit 0
