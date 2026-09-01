# Step by step, no experience needed

This page assumes you have never used a command line and do not want to learn one. It gets
you from a fresh computer to OCR'd pages by copying and pasting a handful of lines.

Setup takes about 20 minutes and you do it **once**. After that, OCR'ing a page is a single
line.

!!! info "What you will be typing into"
    A **terminal** (also called Command Prompt, or Terminal) is a window where you type a
    line, press <kbd>Enter</kbd>, and the computer does it. It looks bare, but you cannot
    break anything by typing the lines on this page.

    Two habits that save trouble: **copy and paste** the lines rather than retyping them,
    and run them **one at a time**, waiting for each to finish. When a command works, it
    usually prints nothing at all — silence is success.

## Before you start: will this work on your computer?

| Your computer | Will it work? |
|---|---|
| Windows | Yes |
| Linux | Yes |
| Mac with an Apple chip (M1, M2, M3, M4…) | Yes |
| Mac with an Intel processor | **No** — see below |

To check a Mac: click the  Apple menu in the top-left corner, then **About This Mac**. If
it says **Chip: Apple M…**, you are fine. If it says **Processor: … Intel …**, this page
will not work on that machine — the software it depends on is no longer published for
Intel Macs. Ask whoever supports your IT about the [Docker option](docker.md), or use a
different computer.

## Step 1 — Install Python

Python is the language TuzkaOCR is written in; it does not come with Windows and is often
outdated on Macs.

=== "Windows"

    1. Go to [python.org/downloads](https://www.python.org/downloads/).
    2. Click the big yellow **Download Python** button and run the file it gives you.
    3. **Important:** on the installer's first screen, tick the box at the bottom that says
       **Add python.exe to PATH**, then click *Install Now*.

    That checkbox is easy to miss and everything later fails without it. If you have already
    installed Python without it, run the installer again and choose *Modify*.

=== "Mac"

    1. Go to [python.org/downloads](https://www.python.org/downloads/).
    2. Click the big yellow **Download Python** button and open the file it gives you.
    3. Click through the installer, accepting the defaults.

=== "Linux"

    Python is almost certainly already installed. Skip to step 2 — you will check in a
    moment anyway.

## Step 2 — Download TuzkaOCR

1. Open the **[latest release page](https://github.com/moravianlibrary/TuzkaOCR/releases/latest)**.
2. Scroll down to the **Assets** section and click **Source code (zip)**.
3. Unzip the file you downloaded. You get a folder named after the version — release
   v1.7.1, for example, unzips to a folder called `TuzkaOCR-1.7.1`.
4. Move that folder somewhere you can find again. Your Documents folder is fine.

This page always shows the newest published version, so the link stays correct as new
versions come out. Every past version is listed on the
[all releases page](https://github.com/moravianlibrary/TuzkaOCR/releases), which is where to
go if a colleague asks you to use a specific one.

!!! warning "Not the green *Code* button"
    The green **Code → Download ZIP** button on the repository's front page gives you
    whatever is being worked on *right now*, which may be halfway through a change. A
    release is a version that was finished and published on purpose. Use the release.

The rest of this page calls that unzipped folder **the TuzkaOCR folder**, since its exact
name changes with the version.

## Step 3 — Open a terminal in that folder

The terminal needs to be "looking at" the TuzkaOCR folder.

=== "Windows"

    1. Open the TuzkaOCR folder in File Explorer, so you can see the files inside it
       (`cli.py`, `README.md`, and so on).
    2. Click once on the **address bar** at the top — the strip showing the folder path.
    3. Type `cmd` over what is there and press <kbd>Enter</kbd>.

    A black window opens, already pointed at the right folder.

=== "Mac"

    1. Open **Terminal** (press <kbd>⌘</kbd><kbd>Space</kbd>, type `terminal`, press
       <kbd>Enter</kbd>).
    2. Type `cd` followed by a single space — do not press Enter yet.
    3. Drag the TuzkaOCR folder from Finder onto the Terminal window. The path fills
       itself in.
    4. Now press <kbd>Enter</kbd>.

=== "Linux"

    Right-click the TuzkaOCR folder and choose **Open in Terminal**.

To confirm Python arrived safely, type this and press <kbd>Enter</kbd>:

=== "Windows"

    ```bat
    python --version
    ```

=== "Mac / Linux"

    ```bash
    python3 --version
    ```

You should see something like `Python 3.12.4`. Any number starting with **3.10 or higher**
is fine. If you instead see "command not found" or "not recognized", Python is not
installed correctly — on Windows that is nearly always the missing PATH checkbox from
step 1.

## Step 4 — One-time setup

Two lines to prepare a private space for TuzkaOCR's files, then one to install it. Run them
in order.

=== "Windows"

    ```bat
    python -m venv .venv
    ```

    ```bat
    .venv\Scripts\activate
    ```

    ```bat
    pip install .
    ```

=== "Mac / Linux"

    ```bash
    python3 -m venv .venv
    ```

    ```bash
    source .venv/bin/activate
    ```

    ```bash
    pip install .
    ```

The third line prints a wall of text for a minute or two as it downloads what it needs.
That is normal. It has worked when you see a line beginning **`Successfully installed`**.

!!! note "The `(.venv)` marker"
    After the second line, your terminal prompt gains a `(.venv)` prefix. That marker means
    TuzkaOCR is available in this window. It matters later — see [coming back
    tomorrow](#coming-back-tomorrow).

Check it worked:

```bash
tuzkaocr --help
```

A list of options means you are done setting up.

## Step 5 — OCR your first page

Put a scanned image — JPEG, PNG, or TIFF — into the TuzkaOCR folder. Say it is
called `page.jpg`. Then:

```bash
tuzkaocr page.jpg --format txt --out page.txt
```

After a few seconds:

```
Done in 2.4s — 37 lines → page.txt
```

`page.txt` is now sitting in the same folder. Open it by double-clicking. That is the text
of your scan.

If your file is named something else, use its real name — and if the name contains spaces,
wrap it in quotes:

```bash
tuzkaocr "scan 001.jpg" --format txt --out "scan 001.txt"
```

## Step 6 — Which setting for which material

One choice matters far more than any other: telling TuzkaOCR what kind of writing it is
looking at. Add `--domain` followed by the right word.

| Your material | Add this |
|---|---|
| Printed books, most scans | nothing — this is the default |
| Kramarky broadsheet prints | `--domain kramarky` |
| Czech handwriting | `--domain handwritten` |
| Old German handwriting (Kurrent, Sütterlin) | `--domain kurrent` |

```bash
tuzkaocr letter.jpg --domain handwritten --format txt --out letter.txt
```

Using the printed setting on handwriting — or the other way round — produces nonsense, so
it is worth getting right. Note that `kramarky` is meant for kramarky broadsheets
specifically; for ordinary newspapers and periodicals, leave the setting off.

## A whole folder of scans

Put your images in a folder — say `scans` — inside the TuzkaOCR folder, then:

```bash
tuzkaocr scans --batch --format txt --out-dir results
```

It works through them one by one, reporting progress and an estimate of the time left:

```
Processing 148 images with 2 worker(s)...
[   1/ 148] 0001.jpg 3.4s  ETA 4.2m
[   2/ 148] 0002.jpg 3.1s  ETA 4.0m
```

The text files appear in a `results` folder, each named after its image. Leave the window
open while it runs; closing it stops the work. A page that fails is reported and skipped,
and the rest carry on.

!!! tip "If your computer becomes sluggish"
    Add `--workers 1` to the end of the line. It processes one page at a time, which is
    slower but much gentler on an older machine.

## Coming back tomorrow

This is the one thing that confuses everybody. Each **new** terminal window starts fresh,
so you have to re-enter the folder and re-activate before `tuzkaocr` exists again:

=== "Windows"

    ```bat
    .venv\Scripts\activate
    ```

=== "Mac / Linux"

    ```bash
    source .venv/bin/activate
    ```

You do **not** repeat `pip install .` — that was genuinely one-time. If you get
`command not found` after reopening the terminal, you have simply skipped this line.

## Want the coordinates too?

Everything above produces plain text. TuzkaOCR can also produce **ALTO XML**, which records
where on the page every single word sits — what a library catalogue or a viewer that
highlights search results needs.

```bash
tuzkaocr page.jpg --out page.alto.xml
```

Do not try to read that file yourself; it is for software. Both at once:

```bash
tuzkaocr page.jpg --format multi --out page
```

That writes `page.alto.xml` and `page.txt` for the price of one.

## When something looks wrong

| What you see | What it means |
|---|---|
| `command not found` / `is not recognized` | The `(.venv)` marker is missing from your prompt. Re-run the activate line above. |
| `No such file or directory` | The image name is not exactly right, or the file is not in this folder. Check spelling, and quote names containing spaces. |
| `running scripts is disabled on this system` (Windows) | You are in PowerShell. Use Command Prompt instead — the `cmd` trick in step 3 — or ask IT to allow local scripts. |
| The text is gibberish | Wrong `--domain` for the material. See [step 6](#step-6-which-setting-for-which-material). |
| The text is mostly right but words are mangled | Likely the scan itself. Below roughly 200 dpi, no setting rescues it. |
| Some lines are missing entirely | Try adding `--height-scale 1.5` to the end of the line. |
| The window closed on its own during a batch | The computer ran out of memory. Add `--workers 1`. |

If you need to ask someone for help, send them: the **exact line you typed**, and the
**last 20 lines** the terminal printed. Those two things resolve most questions
immediately.

## Next steps

- [CLI reference](cli.md) — every available option, once you want more control
- [Troubleshooting](troubleshooting.md) — the technical version of the table above
- [Models and domains](models.md) — what each `--domain` was built for
