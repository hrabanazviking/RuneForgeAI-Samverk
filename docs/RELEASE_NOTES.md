# Samverk 0.1.0 -- release notes

## In plain words

This is the source of Samverk, packed as one file. Samverk is our own version-control forge: the program that holds this source is the program this source builds. Nothing in the package needs Docker, and nothing in it phones home.

To check that the file you downloaded is the file that was packed, save SHA256SUMS.txt beside it and run:

    sha256sum -c SHA256SUMS.txt

(on macOS: shasum -a 256 -c SHA256SUMS.txt). The tarball must answer OK. Any other answer means the file is not the packed bytes and must not be trusted.

This release is not signed yet. That step is Volmarr's to do, with the maintainer key he keeps outside this tree; until he signs, the checksums still prove the files are whole, but nothing here proves whose hands packed them.

## What is in the package

- samverk-0.1.0-source.tar.gz -- 945 source files, 5995227 bytes packed.
- SHA256SUMS.txt -- the checksum of the tarball, in the format S-260 generates for every release.
- These notes.

## Signing

Status: unsigned_remainder. Owner: Volmarr.

No maintainer secret key is present in this environment (the operator keyring holds no secret keys) and Samverk holds no private key by law (S-263). The release ships unsigned; Volmarr signs SHA256SUMS.txt with the maintainer key he holds outside this tree and the detached signature attaches through the S-263 release-signature seam.

## What is honestly not finished

The final claims register (S-399) stands behind these notes. It records as NOT PROVEN: the Windows and macOS platform matrix (F-02, owned by Part XXII), the live server composition (F-10), and a fully green full-suite run (F-11 -- the counted master run names its failures). One README item is OPEN for Volmarr (F-17). None of that is hidden by this packaging; the register ships in docs/.
