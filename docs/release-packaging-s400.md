# Release packaging -- S-400 counted log

Release: samverk-0.1.0 (version 0.1.0)

- Source files packed: 945
- Tarball: samverk-0.1.0-source.tar.gz -- 5995227 bytes
- Tarball SHA-256: d49482e6c3c8b4c4dda9e2a13f93078f2bedf780173d23a702e03497eb015693
- Signing: unsigned_remainder (owner Volmarr)
- Verification round-trip (S-260 machinery): checked 1, ok=True, mismatched=[], missing=[], unexpected=[]

## SHA256SUMS.txt

```
d49482e6c3c8b4c4dda9e2a13f93078f2bedf780173d23a702e03497eb015693  samverk-0.1.0-source.tar.gz
```

## Signing detail

No maintainer secret key is present in this environment (the operator keyring holds no secret keys) and Samverk holds no private key by law (S-263). The release ships unsigned; Volmarr signs SHA256SUMS.txt with the maintainer key he holds outside this tree and the detached signature attaches through the S-263 release-signature seam.
