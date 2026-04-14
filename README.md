# ltc-release-builder

ltc-release-builder is an updated gitian builder script for building Litecoin Core 0.21.x. 
It includes additional features and bugfixes not present in the original gitian-builder script.

We recommend building with docker mode, please see [the Docker installation website](https://docs.docker.com/engine/install/)
for appropriate Docker Desktop for your computer. When building, please make sure to have Docker Desktop open on your system.

### Setup

Replace USERNAME & version number. The version number should be the same as the tag, but without the `v` prefix.

```bash
$ git clone https://github.com/DavidBurkett/ltc-release-builder.git
$ cd ltc-release-builder
$ ./build-release.py --docker --setup USERNAME 0.21.x --disable-apt-cacher
```

### Usage

There are three different build modes, `--build`, `--sign` or `--buildsign`.

Building for specific target OS can be specified by parameter `-o` where `m` is macOS, `w` is Windows and `l` is Linux.

`-j` to specific number of build threads (there is a known issue where too many threads may cause build failures).

`-m` to specify amount of memory to allocate in MB.

**Example**
```
./build-release.py --docker --build losh11 0.21.2rc3 -j 30 -m 10000 --no-commit -o m
```

**Additional help?**
```
./build-release.py --help
```
