#!/usr/bin/env python3

import argparse
import getpass
import os
import subprocess
import sys

def parse_args():
    parser = argparse.ArgumentParser(usage='%(prog)s [options] signer version')
    parser.add_argument('-c', '--commit', action='store_true', dest='commit', help='Indicate that the version argument is for a commit or branch')
    parser.add_argument('-p', '--pull', action='store_true', dest='pull', help='Indicate that the version argument is the number of a github repository pull request')
    parser.add_argument('-u', '--url', dest='url', default='https://github.com/litecoin-project/litecoin', help='Specify the URL of the repository. Default is %(default)s')
    parser.add_argument('-v', '--verify', action='store_true', dest='verify', help='Verify the Gitian build')
    parser.add_argument('-b', '--build', action='store_true', dest='build', help='Do a Gitian build')
    parser.add_argument('-s', '--sign', action='store_true', dest='sign', help='Make signed binaries for Windows and MacOS')
    parser.add_argument('-B', '--buildsign', action='store_true', dest='buildsign', help='Build both signed and unsigned binaries')
    parser.add_argument('-o', '--os', dest='os', default='lwm', help='Specify which Operating Systems the build is for. Default is %(default)s. l for Linux, w for Windows, m for MacOS')
    parser.add_argument('-j', '--jobs', dest='jobs', default='2', help='Number of processes to use. Default %(default)s')
    parser.add_argument('-m', '--memory', dest='memory', default='2000', help='Memory to allocate in MiB. Default %(default)s')
    parser.add_argument('-k', '--kvm', action='store_true', dest='kvm', help='Use KVM instead of LXC')
    parser.add_argument('-d', '--docker', action='store_true', dest='docker', help='Use Docker instead of LXC')
    parser.add_argument('-S', '--setup', action='store_true', dest='setup', help='Set up the Gitian building environment. Uses LXC. If you want to use KVM, use the --kvm option. Only works on Debian-based systems (Ubuntu, Debian)')
    parser.add_argument('-D', '--detach-sign', action='store_true', dest='detach_sign', help='Create the assert file for detached signing. Will not commit anything.')
    parser.add_argument('-n', '--no-commit', action='store_false', dest='commit_files', help='Do not commit anything to git')
    parser.add_argument('--disable-apt-cacher', action='store_true', dest='disable_apt_cacher', help='Apply temporary patch to make-base-vm that disables apt-cacher')
    parser.add_argument('signer', nargs='?', help='GPG signer to sign each build assert file')
    parser.add_argument('version', nargs='?', help='Version number, commit, or branch to build. If building a commit or branch, the -c option must be specified')
    args = parser.parse_args()
    
    if args.commit and args.pull:
        raise Exception('Error: cannot have both commit and pull')

    if args.kvm and args.docker:
        raise Exception('Error: cannot have both kvm and docker')
    
    # Add leading 'v' for tags
    args.commit = ('' if args.commit else 'v') + args.version
    
    # Set build & sign if buildsign
    if args.buildsign:
        args.build = True
        args.sign = True

    # Set OS flags
    args.linux = 'l' in args.os
    args.windows = 'w' in args.os
    args.macos = 'm' in args.os

    args.sign_prog = 'true' if args.detach_sign else 'gpg --batch --yes --detach-sign'

    lsb_rel = subprocess.check_output(['lsb_release', '-cs'])
    args.is_bionic = b'bionic' in lsb_rel
    args.is_debian = any(r in lsb_rel for r in [b'jessie', b'stretch', b'buster', b'bullseye'])
    
    script_name = os.path.basename(sys.argv[0])
    if not args.signer:
        print(script_name+': Missing signer')
        print('Try '+script_name+' --help for more information')
        sys.exit(1)
    if not args.version:
        print(script_name+': Missing version')
        print('Try '+script_name+' --help for more information')
        sys.exit(1)
        
    return args

def setup():
    global args, workdir
    os.chdir(workdir)

    programs = ['ruby', 'git', 'make', 'wget', 'curl']
    if args.kvm:
        programs += ['apt-cacher-ng', 'python-vm-builder', 'qemu-kvm', 'qemu-utils']
    elif args.docker and not os.path.isfile('/lib/systemd/system/docker.service'):
        dockers = ['docker.io', 'docker-ce']
        for i in dockers:
            return_code = subprocess.call(['sudo', 'apt-get', 'install', '-qq', i])
            if return_code == 0:
                break
        if return_code != 0:
            print('Cannot find any way to install Docker.', file=sys.stderr)
            sys.exit(1)
    else:
        programs += ['apt-cacher-ng', 'lxc', 'debootstrap']
    subprocess.check_call(['sudo', 'apt-get', 'install', '-qq'] + programs)
    if not os.path.isdir('gitian.sigs.ltc'):
        subprocess.check_call(['git', 'clone', 'https://github.com/litecoin-project/gitian.sigs.ltc.git'])
    if not os.path.isdir('litecoin-detached-sigs'):
        subprocess.check_call(['git', 'clone', 'https://github.com/litecoin-project/litecoin-detached-sigs.git'])
    if not os.path.isdir('gitian-builder'):
        subprocess.check_call(['git', 'clone', 'https://github.com/devrandom/gitian-builder.git'])
        if args.disable_apt_cacher:
            os.chdir(os.path.join(workdir, 'gitian-builder'))
            subprocess.check_call(['git', 'am', '../0001-Disable-apt-cacher.patch'])
        
    # Make Gitian VM
    os.chdir(os.path.join(workdir, 'gitian-builder'))
    make_image_prog = ['bin/make-base-vm', '--suite', 'bionic', '--arch', 'amd64']
    if args.docker:
        make_image_prog += ['--docker']
    elif not args.kvm:
        make_image_prog += ['--lxc']
    subprocess.check_call(make_image_prog)
    os.chdir(workdir)
    
    if args.is_bionic and not args.kvm and not args.docker:
        subprocess.check_call(['sudo', 'sed', '-i', 's/lxcbr0/br0/', '/etc/default/lxc-net'])
        print('Reboot is required')
        sys.exit(0)

    # Download Mac SDK
    MAC_SDK = 'Xcode-11.3.1-11C505-extracted-SDK-with-libcxx-headers.tar.gz'
    os.chdir(os.path.join(workdir, 'gitian-builder'))
    os.makedirs('inputs', exist_ok=True)
    if args.macos and not os.path.isfile('inputs/{}'.format(MAC_SDK)):
        subprocess.check_call(['wget', '-O', 'inputs/{}'.format(MAC_SDK), 'https://bitcoincore.org/depends-sources/sdks/{}'.format(MAC_SDK)])
        subprocess.check_call(["echo '436df6dfc7073365d12f8ef6c1fdb060777c720602cc67c2dcf9a59d94290e38 inputs/{}' | sha256sum -c".format(MAC_SDK)], shell=True)

    # Download osslsigncode-2.0
    subprocess.check_call(['wget', '-O', 'inputs/osslsigncode-2.0.tar.gz', 'https://github.com/mtrojnar/osslsigncode/archive/2.0.tar.gz'])
    subprocess.check_call(["echo '5a60e0a4b3e0b4d655317b2f12a810211c50242138322b16e7e01c6fbb89d92f inputs/osslsigncode-2.0.tar.gz' | sha256sum -c"], shell=True)

def build():
    global args, workdir

    os.makedirs(os.path.join(workdir, 'litecoin-binaries', args.version), exist_ok=True)
    os.chdir(os.path.join(workdir, 'gitian-builder'))

    if args.linux:
        print('\nCompiling ' + args.version + ' Linux')
        subprocess.check_call(['bin/gbuild', '-j', args.jobs, '-m', args.memory, '--commit', 'litecoin='+args.commit, '--url', 'litecoin='+args.url, '../gitian-descriptors/gitian-linux.yml'])
        preset_gpg_passphrase()
        subprocess.check_call(['bin/gsign', '-p', args.sign_prog, '--signer', args.signer, '--release', args.version+'-linux', '--destination', '../gitian.sigs.ltc/', '../gitian-descriptors/gitian-linux.yml'])
        subprocess.check_call('mv build/out/litecoin-*.tar.gz build/out/src/litecoin-*.tar.gz ../litecoin-binaries/'+args.version, shell=True)

    if args.windows:
        print('\nCompiling ' + args.version + ' Windows')
        subprocess.check_call(['bin/gbuild', '-j', args.jobs, '-m', args.memory, '--commit', 'litecoin='+args.commit, '--url', 'litecoin='+args.url, '../gitian-descriptors/gitian-win.yml'])
        preset_gpg_passphrase()
        subprocess.check_call(['bin/gsign', '-p', args.sign_prog, '--signer', args.signer, '--release', args.version+'-win-unsigned', '--destination', '../gitian.sigs.ltc/', '../gitian-descriptors/gitian-win.yml'])
        subprocess.check_call('mv build/out/litecoin-*-win-unsigned.tar.gz inputs/', shell=True)
        subprocess.check_call('mv build/out/litecoin-*.zip build/out/litecoin-*.exe build/out/src/litecoin-*.tar.gz ../litecoin-binaries/'+args.version, shell=True)

    if args.macos:
        print('\nCompiling ' + args.version + ' MacOS')
        subprocess.check_call(['bin/gbuild', '-j', args.jobs, '-m', args.memory, '--commit', 'litecoin='+args.commit, '--url', 'litecoin='+args.url, '../gitian-descriptors/gitian-osx.yml'])
        preset_gpg_passphrase()
        subprocess.check_call(['bin/gsign', '-p', args.sign_prog, '--signer', args.signer, '--release', args.version+'-osx-unsigned', '--destination', '../gitian.sigs.ltc/', '../gitian-descriptors/gitian-osx.yml'])
        subprocess.check_call('mv build/out/litecoin-*-osx-unsigned.tar.gz inputs/', shell=True)
        subprocess.check_call('mv build/out/litecoin-*.tar.gz build/out/litecoin-*.dmg build/out/src/litecoin-*.tar.gz ../litecoin-binaries/'+args.version, shell=True)

    if args.commit_files:
        print('\nCommitting '+args.version+' Unsigned Sigs\n')
        os.chdir(os.path.join(workdir, 'gitian.sigs.ltc'))
        subprocess.check_call(['git', 'add', args.version+'-linux/'+args.signer])
        subprocess.check_call(['git', 'add', args.version+'-win-unsigned/'+args.signer])
        subprocess.check_call(['git', 'add', args.version+'-osx-unsigned/'+args.signer])
        subprocess.check_call(['git', 'commit', '-m', 'Add '+args.version+' unsigned sigs for '+args.signer])

def sign():
    global args, workdir
    os.chdir(os.path.join(workdir, 'gitian-builder'))
    
    # Set GPG Passphrase
    preset_gpg_passphrase()
    
    if args.windows:
        print('\nSigning ' + args.version + ' Windows')
        subprocess.check_call('cp inputs/litecoin-' + args.version + '-win-unsigned.tar.gz inputs/litecoin-win-unsigned.tar.gz', shell=True)
        subprocess.check_call(['bin/gbuild', '--skip-image', '--upgrade', '--commit', 'signature='+args.commit, '../gitian-descriptors/gitian-win-signer.yml'])
        subprocess.check_call(['bin/gsign', '-p', args.sign_prog, '--signer', args.signer, '--release', args.version+'-win-signed', '--destination', '../gitian.sigs.ltc/', '../gitian-descriptors/gitian-win-signer.yml'])
        subprocess.check_call('mv build/out/litecoin-*win64-setup.exe ../litecoin-binaries/'+args.version, shell=True)

    if args.macos:
        print('\nSigning ' + args.version + ' MacOS')
        subprocess.check_call('cp inputs/litecoin-' + args.version + '-osx-unsigned.tar.gz inputs/litecoin-osx-unsigned.tar.gz', shell=True)
        subprocess.check_call(['bin/gbuild', '--skip-image', '--upgrade', '--commit', 'signature='+args.commit, '../gitian-descriptors/gitian-osx-signer.yml'])
        subprocess.check_call(['bin/gsign', '-p', args.sign_prog, '--signer', args.signer, '--release', args.version+'-osx-signed', '--destination', '../gitian.sigs.ltc/', '../gitian-descriptors/gitian-osx-signer.yml'])
        subprocess.check_call('mv build/out/litecoin-osx-signed.dmg ../litecoin-binaries/'+args.version+'/litecoin-'+args.version+'-osx.dmg', shell=True)

    if args.commit_files:
        print('\nCommitting '+args.version+' Signed Sigs\n')
        os.chdir(os.path.join(workdir, 'gitian.sigs.ltc'))
        subprocess.check_call(['git', 'add', args.version+'-win-signed/'+args.signer])
        subprocess.check_call(['git', 'add', args.version+'-osx-signed/'+args.signer])
        subprocess.check_call(['git', 'commit', '-a', '-m', 'Add '+args.version+' signed binary sigs for '+args.signer])

def verify():
    global args, workdir
    rc = 0
    
    os.chdir(os.path.join(workdir, 'gitian.sigs.ltc'))
    subprocess.check_call(['git', 'pull'])
    
    os.chdir(os.path.join(workdir, 'gitian-builder'))

    print('\nVerifying v'+args.version+' Linux\n')
    if subprocess.call(['bin/gverify', '-v', '-d', '../gitian.sigs.ltc/', '-r', args.version+'-linux', '../gitian-descriptors/gitian-linux.yml']):
        print('Verifying v'+args.version+' Linux FAILED\n')
        rc = 1

    print('\nVerifying v'+args.version+' Windows\n')
    if subprocess.call(['bin/gverify', '-v', '-d', '../gitian.sigs.ltc/', '-r', args.version+'-win-unsigned', '../gitian-descriptors/gitian-win.yml']):
        print('Verifying v'+args.version+' Windows FAILED\n')
        rc = 1

    print('\nVerifying v'+args.version+' MacOS\n')
    if subprocess.call(['bin/gverify', '-v', '-d', '../gitian.sigs.ltc/', '-r', args.version+'-osx-unsigned', '../gitian-descriptors/gitian-osx.yml']):
        print('Verifying v'+args.version+' MacOS FAILED\n')
        rc = 1

    print('\nVerifying v'+args.version+' Signed Windows\n')
    if subprocess.call(['bin/gverify', '-v', '-d', '../gitian.sigs.ltc/', '-r', args.version+'-win-signed', '../gitian-descriptors/gitian-win-signer.yml']):
        print('Verifying v'+args.version+' Signed Windows FAILED\n')
        rc = 1

    print('\nVerifying v'+args.version+' Signed MacOS\n')
    if subprocess.call(['bin/gverify', '-v', '-d', '../gitian.sigs.ltc/', '-r', args.version+'-osx-signed', '../gitian-descriptors/gitian-osx-signer.yml']):
        print('Verifying v'+args.version+' Signed MacOS FAILED\n')
        rc = 1

    return rc


def preset_gpg_passphrase():
    global args, gpg_password
    
    subprocess.call(['gpgconf', '--kill', 'gpg-agent'])

    if args.is_debian:
        try:
            subprocess.call(['rm', '-r', '/var/run/user/0/gnupg/*gpg-agent*'])
        except Exception as e:
            print('Error clearing gpg-agents: {0}'.format(e))

    subprocess.check_call(['gpg-agent', '--daemon', '--allow-preset-passphrase'])
    
    keygrips = subprocess.run("gpg --fingerprint --with-keygrip {} | awk '/Keygrip/ {{ print $3}}'".format(args.signer), shell=True, text=True, stdout=subprocess.PIPE).stdout.splitlines()
    
    for keygrip in keygrips:
        subprocess.check_call('echo "{0}"  | /usr/lib/gnupg/gpg-preset-passphrase --preset {1}'.format(gpg_password, keygrip), shell=True)
    
def main():
    global args, workdir, gpg_password
    
    args = parse_args()
    workdir = os.getcwd()

    # Ensure no more than one environment variable for gitian-builder (USE_LXC, USE_VBOX, USE_DOCKER) is set as they
    # can interfere (e.g., USE_LXC being set shadows USE_DOCKER; for details see gitian-builder/libexec/make-clean-vm).
    os.environ['USE_LXC'] = ''
    os.environ['USE_VBOX'] = ''
    os.environ['USE_DOCKER'] = ''
    if args.docker:
        os.environ['USE_DOCKER'] = '1'
    elif not args.kvm:
        os.environ['USE_LXC'] = '1'
        if 'GITIAN_HOST_IP' not in os.environ.keys():
            os.environ['GITIAN_HOST_IP'] = '10.0.3.1'
        if 'LXC_GUEST_IP' not in os.environ.keys():
            os.environ['LXC_GUEST_IP'] = '10.0.3.5'
    
    if args.build or args.sign:
        gpg_password = getpass.getpass("GPG Password: ") # TODO: First check if key is actually password protected

    if args.setup:
        setup()

    if not args.build and not args.sign and not args.verify:
        sys.exit(0)

    if args.pull:
        os.chdir('../gitian-builder/inputs/litecoin')
        subprocess.check_call(['git', 'fetch', args.url, 'refs/pull/'+args.version+'/merge'])
        args.commit = subprocess.check_output(['git', 'show', '-s', '--format=%H', 'FETCH_HEAD'], universal_newlines=True, encoding='utf8').strip()
        args.version = 'pull-' + args.version
    
    print('args.commit=' + args.commit)
    print('args.version=' + args.version)

    os.chdir(os.path.join(workdir, 'gitian-builder'))
    subprocess.check_call(['git', 'pull'])

    if args.build:
        build()

    if args.sign:
        sign()

    if args.verify:
        sys.exit(verify())

if __name__ == '__main__':
    main()
