# Brainfuck Chat Application

A 1:1 chat application where **the entire application logic is written in Brainfuck** — an esoteric programming language with only 8 commands. Two people open terminals, run the same program, and send messages back and forth freely — no waiting for a reply before sending the next message.

## The Problem

Brainfuck has no networking and no concurrency. It can read one byte from stdin (`,`) and write one byte to stdout (`.`). That's it. Building a chat application in Brainfuck is, by the language's standard definition, impossible.

## The Solution

I designed a **minimal language extension**: a custom Python interpreter that understands standard Brainfuck plus exactly 5 new commands — 4 for TCP sockets and 1 for concurrency. The interpreter is infrastructure (like how RStudio is infrastructure for R). The application — `chat.bf` — is pure Brainfuck.

This approach has strong precedent. Projects like [Netfuck](https://github.com/artagnon/netfuck), Trainfuck, and [Brainfuck--](https://esolangs.org/wiki/Brainfuck--) all extend BF with networking in exactly this way. The BF community treats extended interpreters as legitimate.

## Command Reference

### Standard Brainfuck (8 commands)

| Command | Meaning |
|---------|---------|
| `>` | Move data pointer right |
| `<` | Move data pointer left |
| `+` | Increment current cell |
| `-` | Decrement current cell |
| `.` | Output current cell as ASCII to stdout |
| `,` | Read one byte from stdin into current cell |
| `[` | If current cell is 0, jump to matching `]` |
| `]` | If current cell is not 0, jump back to matching `[` |

### Extended Commands (5 commands)

| Command | Name | Meaning |
|---------|------|---------|
| `@` | OPEN | Open a TCP socket (server: bind + listen + accept / client: connect) |
| `~` | RECV | Read one byte from the network into the current cell |
| `^` | SEND | Write one byte from the current cell to the network |
| `!` | CLOSE | Close the socket |
| `#` | FORK | Split execution into two concurrent threads |

**Why these 5?** The first four mirror how BF already handles I/O: `,` reads from stdin, `.` writes to stdout. I added the equivalent for network I/O: `~` reads from the network, `^` writes to the network. Plus open/close for connection lifecycle. The fifth — `#` — gives BF access to concurrency the same way `@~^!` give it access to networking. The interpreter handles thread creation (infrastructure), but what each thread does, when to quit, and how to format output is written entirely in BF.

## How to Run

**Requirements:** Python 3.6+ (no external dependencies).

### Quick test (verify the interpreter works)

```bash
python3 bf.py examples/hello.bf
# Output: Hello World!
```

### Run the chat

**Terminal 1 — Start the server:**
```bash
python3 bf.py --server chat.bf --port 8888
```
You'll see: `Waiting for connection on port 8888...`

**Terminal 2 — Connect the client:**
```bash
python3 bf.py --client chat.bf --host localhost --port 8888
```
You'll see: `Connected to localhost:8888!`

**Now chat!** Both sides can send messages at any time — no need to wait for a reply. Type your message and press Enter to send. Incoming messages appear with the `Remote:` prefix so you can tell them apart from what you typed.

```
Terminal 1 (server):                 Terminal 2 (client):
Waiting for connection on port 8888...
Connected! (127.0.0.1:54321)         Connected to localhost:8888!
                                     Hello!
Remote: Hello!
                                     Anyone there?
Remote: Anyone there?
Hey! I'm here.                       Remote: Hey! I'm here.
What's up?                           Remote: What's up?
                                     Not much!
Remote: Not much!
```

**To quit:** Press Enter without typing anything. You'll see `Goodbye!` and the other side will see `Connection closed.` Both sides can also use `Ctrl+C`.

## How It Works

### Architecture

The program has two halves, separated by the `#` (fork) command:

```
@ [receive loop] # [send loop] !
```

1. `@` opens the TCP socket (the interpreter handles server vs client based on CLI flags)
2. `#` splits execution into two concurrent threads, each with its own memory tape
3. **Thread 1** (receive): loops forever, printing `Remote: ` then reading bytes from the network and displaying them
4. **Thread 2** (send): loops forever, reading bytes from the keyboard and sending them over the network
5. `!` closes the socket after both threads finish

Both threads share the TCP connection but have completely independent memory tapes. This is safe because one thread only reads from the socket and the other only writes to it.

### Why One Program for Both Sides

With concurrent architecture, there is no "who sends first" — both sides send and receive simultaneously. The protocol is inherently symmetric, so a single `chat.bf` program handles both roles. The `--server` or `--client` flag only affects how the interpreter opens the socket; the BF application logic is identical.

### Why No "You:" Label

The terminal already echoes what you type — you can see your own keystrokes on screen. Labeling your own messages with "You:" would be redundant. Only incoming messages need a label (`Remote:`) to distinguish them from your own typing. This keeps the output clean and avoids the complexity of coordinating label output between two concurrent threads sharing the same terminal.

### The Chat Protocol

The protocol is **concurrent** and **newline-delimited**:

- Either side can send a message at any time by typing and pressing Enter
- Each message is terminated by a newline (`\n`, ASCII 10)
- The receive thread displays incoming messages with the `Remote: ` prefix
- The send thread reads keyboard input and forwards it to the network

**Why newline (`\n`) as the message boundary?** A single Enter press sends the message — just like WhatsApp, Slack, or iMessage. This keeps the BF logic simple: read bytes until one equals 10 (newline), then print a newline and loop back for the next message.

### The Memory Tape Layout

In Brainfuck, there are no variable names — just a tape of numbered cells. Each thread gets its own tape. I planned this layout before writing a single instruction:

```
Cell 0: WORK CELL       — the byte currently being read/sent
Cell 1: LOOP FLAG       — 1 = keep running, 0 = exit (set by empty-turn quit in the send thread)
Cell 2: SEND NL FLAG    — (send thread only) 1 = send the newline, 0 = suppress it (quit case)
Cell 3: SCRATCH COUNTER — loop counter for ASCII multiplication during label construction
Cell 4: ACCUMULATOR     — product accumulator during label construction
                          (in the send thread, also serves as the quit flag)
```

Cell 2 is unused in the receive thread. The ASCII label-building code uses `>>>` to reach cells 3 and 4 from cell 0, which skips cell 2.

**Why a quit flag in cell 4?** At the start of each send turn, cell 4 is set to 1 (assume empty turn). When any non-newline byte is sent, cell 4 is zeroed. After the message is complete, the quit check examines cell 4: if it's still 1, the user pressed Enter without typing anything — the quit signal. This is genuine conditional logic in BF, not just byte-forwarding.

**Cell 2 (send-newline flag):** After the inner send loop finds a newline, the program needs to decide: send the newline (normal message) or suppress it (quit). BF has no "if-else" — only "if nonzero." I solve this with a two-flag pattern: cell 2 starts at 1 (assume send). If cell 4 is 1 (quit), the quit handler zeros both cell 2 and cell 1. Then the send-newline check runs: if cell 2 is still 1, restore the newline and send it. This means the other side never sees a blank `Remote:` line when you quit.

### The Newline Detection Trick

The cleverest part of the BF code. The challenge: how do you detect when a byte is a newline (value 10)? BF's only conditional (`[ ]`) checks "is this cell zero?" — not "does this cell equal 10."

**The trick:** Subtract 10. If the result is 0, it was a newline.

But subtracting destroys the original value! **Solution:** Add 10 back before processing.

```brainfuck
~              Read byte from network
----------     Subtract 10
[              If non-zero (not newline):
  ++++++++++     Add 10 back (restore original byte)
  .              Print it
  ~              Read next byte
  ----------     Subtract 10
]              Repeat until newline
```

### Raw Terminal Mode

By default, the terminal echoes every keystroke automatically — the interpreter has no control over where characters appear on screen. When a remote message arrives mid-typing, the output would be garbled: `How are yRemote: Hello!`.

I solve this by switching the terminal to **raw mode** (`tty.setraw()`), which tells the terminal to stop echoing keystrokes. The interpreter then echoes each keystroke itself, tracking what the user has typed so far in an input buffer. When the receive thread has a complete message to display, it:

1. Clears the current line (where the user's typing is)
2. Prints the incoming `Remote:` message
3. Reprints whatever the user had typed, restoring their cursor position

The interpreter manages the display the same way it manages the network — giving BF programs access to capabilities the language doesn't natively have, without moving application logic out of BF. The BF program still uses `,` to read and `^` to send. It doesn't know or care that the interpreter is handling the display.

### `Remote: ` Label Construction

The label is built entirely in BF using ASCII multiplication loops — no interpreter support needed. Each character is constructed by multiplying two small numbers and adding a remainder:

```brainfuck
>>>++++++++[>++++++++++<-]>++.[-]<[-]<<<
```

This builds 'R' (ASCII 82): move to cell 3, set it to 8, multiply 8 × 10 into cell 4 by looping, add 2 to get 82, print, clean up, return to cell 0.

### The Complete Program

The program contains **497 BF instructions** and is extensively commented inline (BF ignores all non-command characters, so comments are free). The structure:

```
@  [Remote: label]  [receive loop]  #  [quit flag]  [send loop]  [conditional newline + quit check]  !
```

See `chat.bf` for the fully annotated code with explanations of every instruction.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Python for the interpreter** | Readable, no compilation needed, sockets are built-in. The interpreter should be boring infrastructure, not clever code. |
| **TCP (not UDP)** | Reliable, ordered, connection-oriented. Chat messages must arrive in order and not get lost. |
| **Concurrent via `#`** | `#` gives BF access to concurrency the same way `@~^!` give it access to networking. The interpreter handles thread creation; the BF program defines what each thread does. |
| **Newline delimiter** | A single Enter press sends the message — the same UX as any modern chat app. Keeps the BF logic minimal: read bytes until newline, then loop. |
| **5 extended commands** | Minimal extension principle. `@~^!` = open/recv/send/close for sockets. `#` = fork for concurrency. Each command does one thing. |
| **No "You:" label** | The terminal echoes your keystrokes — labeling your own messages is redundant. Only incoming messages need `Remote:` to distinguish them. This eliminates terminal interleaving issues between concurrent threads. |
| **Single program file** | With concurrent architecture, the protocol is symmetric — both sides do the same thing. A single `chat.bf` run with `--server` or `--client` flags is more elegant than duplicating code. |
| **Interpreter-level disconnect handling** | When the socket closes, the interpreter exits the threads and prints "Connection closed." Connection lifecycle is infrastructure, not application logic. |
| **Raw terminal mode** | The interpreter takes control of keystroke echoing and display. When a remote message arrives mid-typing, it clears the line, prints the message, and restores the user's partial input. This prevents interleaving without moving application logic out of BF. |
| **Line-buffered output** | Each thread buffers characters and prints complete lines atomically. This prevents messages from interleaving mid-word. |
| **Host/port as CLI args** | Keeps the BF program portable. Connect to any address without rewriting BF code. |
| **`Remote: ` label in BF** | Built in pure BF using ASCII multiplication loops. Shows that BF can construct arbitrary ASCII output, not just forward bytes. |
| **Empty-turn quit** | Pressing Enter without typing anything means cell 4 (quit flag) stays at 1. The BF program detects this and exits the send loop cleanly, which triggers socket close and exits the receive thread. |

## Known Limitations

- **Single connection** — The server handles exactly one client. Multi-user would require interpreter-level connection management.
- **ASCII only** — Bytes above 127 (emoji, accented characters) send and receive correctly as raw bytes, but the terminal display depends on the locale encoding. BF cells are 8-bit, so values 0–255 are all valid.

## Project Structure

```
BF_chat/
├── bf.py              # Custom BF interpreter with threading (Python, ~400 lines)
├── chat.bf            # Chat application (Brainfuck, 497 instructions, extensively commented)
├── README.md          # This file
└── examples/
    └── hello.bf       # Hello World — verifies the base interpreter
```
