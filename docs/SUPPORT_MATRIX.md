# Support matrix (S-405)

In plain words: this is Samverk's cross-platform
promise, written down and ratified. The server is
promised on Linux, Windows and macOS, on x86-64
and ARM64 CPUs, with the Raspberry Pi 5 as the
floor -- nothing weaker is promised. The matrix
lives in research file 45
(`research/45-cross-platform-architecture.md`);
this document is its rendered form, judged from
the law module `samverk/support_matrix.py`.

Every cell is marked NOT PROVEN. That is the
honest state at ratification: a cell is PROVEN
only when its battery has run in that cell, and
no cell's Part XXII run has been counted yet --
not even Linux x86-64, where the development
happened and where S-399 still judged the matrix
claim (F-02) NOT PROVEN. Cells flip on counted
runs, never on wording.

The battery is `tests/test_support_matrix.py`;
the runner is `tools/run_support_matrix.py`;
the counted log ships at
`docs/support-matrix-s405.md`.

## Census

- Matrix cells: 12
- NOT PROVEN: 12 (every cell)
- OS x CPU cells: 4
- Filesystem cells: 2
- Deployment cells: 2
- Service-form cells: 3
- Reach cells: 1
- Schema 140, taxonomy 142 stand (no migration,
  no new taxonomy event in this slice)

## The promise

- Server operating systems: Linux, Windows, macOS
- CPUs: x86-64 and ARM64
- Floor: Raspberry Pi 5 -- nothing weaker promised
- Not promised: Windows on ARM64, macOS on x86-64,
  hardware weaker than a Raspberry Pi 5
- Installs are native on every platform; no Docker
  anywhere in the promise (standing law)

## The cells

### linux-x86-64 -- Server on Linux, x86-64

- Status: NOT PROVEN
- Dimension: os_cpu
- Platform: Linux
- CPU / surface: x86-64
- Floor: ordinary laptop, desktop or server
- Flips at: S-416
- Proof that flips it: The full battery (S-394) executed green on a Linux x86-64 host and counted as this cell's run at the portability gate
- Note: Development and every counted run to date happened on Linux x86-64 hosts, and S-399 still judged the matrix claim F-02 NOT PROVEN: no run has been counted as this cell's Part XXII proof. Ratified NOT PROVEN like every other cell.

### linux-arm64-pi5 -- Server on Linux, ARM64 -- Raspberry Pi 5 floor

- Status: NOT PROVEN
- Dimension: os_cpu
- Platform: Linux
- CPU / surface: ARM64
- Floor: Raspberry Pi 5 (the floor: nothing weaker is promised)
- Flips at: S-415
- Proof that flips it: The full battery (S-394) executed green on the Raspberry Pi 5, counted and recorded
- Note: Pi-class performance budgets were MEASURED on a Raspberry Pi 5 at S-395; measured budgets are not a battery run. The cell flips only at S-415. Hardware weaker than a Pi 5 is outside the promise.

### windows-x86-64 -- Server on Windows, x86-64

- Status: NOT PROVEN
- Dimension: os_cpu
- Platform: Windows
- CPU / surface: x86-64
- Floor: ordinary laptop, desktop or server
- Flips at: S-416
- Proof that flips it: The full battery executed green on Windows x86-64 and counted at the portability gate
- Note: No Samverk battery has ever run on Windows. Git, SSH and service behaviour differ there (research 45); a Linux pass claims nothing about this cell. Its service form is the windows-service cell (S-410).

### macos-arm64 -- Server on macOS, Apple silicon

- Status: NOT PROVEN
- Dimension: os_cpu
- Platform: macOS
- CPU / surface: ARM64
- Floor: Apple silicon Mac
- Flips at: S-416
- Proof that flips it: The full battery executed green on macOS on Apple silicon and counted at the portability gate
- Note: The second ARM64 home. No Samverk battery has ever run on macOS. Its service form is the launchd-service cell (S-411). macOS on Intel (x86-64) is not promised and has no cell.

### fs-case-sensitive -- Repository storage on case-sensitive filesystems

- Status: NOT PROVEN
- Dimension: filesystem
- Platform: filesystem
- CPU / surface: n/a
- Floor: the filesystems Linux servers ship by default
- Flips at: S-408
- Proof that flips it: The filesystem battery (two names differing only by case handled deterministically) run green on a case-sensitive filesystem
- Note: Half of S-408's filesystem law. Correctness here is the common case today but is not counted as this cell's proof until S-408 runs it as one.

### fs-case-insensitive -- Repository storage on case-insensitive filesystems

- Status: NOT PROVEN
- Dimension: filesystem
- Platform: filesystem
- CPU / surface: n/a
- Floor: the default filesystems of Windows and macOS
- Flips at: S-408
- Proof that flips it: The filesystem battery run green on a case-insensitive filesystem, the Foo/foo collision handled deterministically
- Note: The hard half of S-408's law and a named threat in research 45: two repositories whose names differ only by case collide on these filesystems. Never exercised by any counted run.

### deploy-real-sshd -- Real SSH daemon deployment

- Status: NOT PROVEN
- Dimension: deployment
- Platform: deployment
- CPU / surface: n/a
- Floor: a stock sshd on a promised OS
- Flips at: Part XXII (S-415/S-416 cells)
- Proof that flips it: The transport battery runs against a real sshd in a proven cell, counted green
- Note: Carries the scoped remainder of claim F-01 (S-399): stock-git smart-HTTP and SSH forced-command harnesses are green, the real-sshd cell was skipped on the proving host and remains NOT PROVEN. Research 45 gives real deployment its own cells.

### deploy-real-http -- Real HTTP deployment

- Status: NOT PROVEN
- Dimension: deployment
- Platform: deployment
- CPU / surface: n/a
- Floor: the server answering real HTTP clients on a promised OS
- Flips at: Part XXII (S-415/S-416 cells)
- Proof that flips it: The battery's HTTP transport runs counted green against the real server in a proven cell
- Note: Research 45: Python http.server production caveats apply on every OS, so infrastructure security needs platform-by-platform proof. Live-instance walks on Linux exist (S-397); no Part XXII cell run has been counted.

### service-systemd -- Linux service form: systemd

- Status: NOT PROVEN
- Dimension: service
- Platform: Linux
- CPU / surface: any promised CPU
- Floor: a systemd Linux host
- Flips at: S-412
- Proof that flips it: The S-348 systemd units re-verified as one of three equal citizens, counted
- Note: The units exist (S-348); S-412 re-verifies them as an equal citizen beside the Windows and launchd forms -- no feature may exist on Linux that the service model forbids elsewhere.

### service-windows -- Windows service form: native Windows service

- Status: NOT PROVEN
- Dimension: service
- Platform: Windows
- CPU / surface: x86-64
- Floor: a Windows host, no Docker and no WSL requirement
- Flips at: S-410
- Proof that flips it: Samverk installed and running as a native Windows service, install walk documented to Part XVIII's standard, counted
- Note: Nothing exists yet: no Windows service wrapper, no install walk. Native install only -- the standing No Docker law binds this cell in its own words (S-410).

### service-launchd -- macOS service form: launchd

- Status: NOT PROVEN
- Dimension: service
- Platform: macOS
- CPU / surface: ARM64
- Floor: an Apple silicon Mac
- Flips at: S-411
- Proof that flips it: Samverk installed and running under launchd, install walk documented to Part XVIII's standard, counted
- Note: Nothing exists yet: no launchd plist, no install walk. Service packaging is a platform-specific adapter, never a container workaround (research 45).

### browser-device-reach -- Browser and device reach of the web UI

- Status: NOT PROVEN
- Dimension: reach
- Platform: web UI
- CPU / surface: n/a
- Floor: current Chrome, Firefox, Safari and Edge; phone and tablet browsers
- Flips at: S-414
- Proof that flips it: The web UI verified in each named browser and on phone and tablet browsers (small screens, touch targets per S-386), counted
- Note: S-414's own words: the device matrix is the test list. No cross-browser verification has been counted; desktop-only development proves nothing about this cell.

## How cells flip

- S-415 runs the full battery on the Raspberry
  Pi 5: the linux-arm64-pi5 cell flips on its
  counted run, and no other cell moves.
- S-416 is the portability gate: the full battery
  on Windows x86-64 and macOS (Apple silicon),
  and the claims register is published with every
  promised cell PROVEN with its counted run or
  NOT PROVEN in plain words.
- S-408 owns the filesystem cells, S-410..S-412
  the three service forms as equal citizens,
  S-414 the browser and device reach cell.
- A budget measured on a class (S-413) claims
  nothing about another class, and a cell proven
  on one platform claims nothing about any other.
