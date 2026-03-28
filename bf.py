#!/usr/bin/env python3
"""
Custom Brainfuck interpreter with TCP socket and threading extensions.

Standard BF commands: > < + - . , [ ]
Extended commands:    @ (open socket) ~ (recv byte) ^ (send byte) ! (close socket)
                     # (fork into two concurrent threads)

Usage:
  python bf.py program.bf                                       # Run a standard BF program
  python bf.py --server chat.bf --port 8888                     # Run as chat server
  python bf.py --client chat.bf --host localhost --port 8888    # Run as chat client
"""

import sys
import os
import socket
import argparse
import threading
import tty
import termios

VALID_COMMANDS = set('><+-.,[]@~^!#')
TAPE_SIZE = 30000


def parse_args():
    parser = argparse.ArgumentParser(description='Brainfuck interpreter with networking extensions')
    parser.add_argument('program', help='Path to the .bf program file')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--server', action='store_true', help='Run in server mode (listen for connections)')
    mode.add_argument('--client', action='store_true', help='Run in client mode (connect to server)')
    parser.add_argument('--host', default='localhost', help='Host to connect to (client mode, default: localhost)')
    parser.add_argument('--port', type=int, default=8888, help='Port number (default: 8888)')
    return parser.parse_args()


def load_program(filepath):
    """Load a BF program from file, keeping only valid commands."""
    try:
        with open(filepath, 'r') as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found.", file=sys.stderr)
        sys.exit(1)
    return [ch for ch in source if ch in VALID_COMMANDS]


def precompute_brackets(program):
    """Build a jump table mapping each [ to its matching ] and vice versa."""
    stack = []
    jumps = {}
    for i, cmd in enumerate(program):
        if cmd == '[':
            stack.append(i)
        elif cmd == ']':
            if not stack:
                print(f"Error: Unmatched ']' at position {i}.", file=sys.stderr)
                sys.exit(1)
            open_pos = stack.pop()
            jumps[open_pos] = i
            jumps[i] = open_pos
    if stack:
        print(f"Error: Unmatched '[' at position {stack[-1]}.", file=sys.stderr)
        sys.exit(1)
    return jumps


def open_socket(args):
    """Open a TCP socket based on mode (server or client)."""
    if args.server:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(('0.0.0.0', args.port))
        server_sock.listen(1)
        print(f"Waiting for connection on port {args.port}...")
        conn, addr = server_sock.accept()
        print(f"Connected! ({addr[0]}:{addr[1]})")
        server_sock.close()
        return conn
    elif args.client:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((args.host, args.port))
        except ConnectionRefusedError:
            print(f"Error: Could not connect to {args.host}:{args.port}. Is the server running?", file=sys.stderr)
            sys.exit(1)
        print(f"Connected to {args.host}:{args.port}!")
        return sock
    else:
        print("Error: @ command requires --server or --client mode.", file=sys.stderr)
        sys.exit(1)


def run_section(program, conn, disconnect, print_lock, name, shared):
    """Run a BF program section in its own thread with its own tape.

    shared is a dict with:
        'input': str  — what the user has typed so far (send thread writes, recv thread reads)
        'raw': bool   — whether raw terminal mode is active
    """
    jumps = precompute_brackets(program)
    tape = [0] * TAPE_SIZE
    dp = 0
    ip = 0
    line_buffer = []
    input_buffer = []

    def flush_buffer():
        """Flush the line buffer to stdout under the print lock."""
        if not line_buffer:
            return
        text = ''.join(line_buffer)
        line_buffer.clear()
        with print_lock:
            if name == "recv" and shared['raw'] and shared['input']:
                # Clear the user's typing line, print our message, restore their typing
                sys.stdout.write('\r\033[2K' + text + shared['input'])
            else:
                sys.stdout.write(text)
            sys.stdout.flush()

    while ip < len(program) and not disconnect.is_set():
        cmd = program[ip]

        if cmd == '>':
            dp += 1
            if dp >= TAPE_SIZE:
                return
        elif cmd == '<':
            dp -= 1
            if dp < 0:
                return
        elif cmd == '+':
            tape[dp] = (tape[dp] + 1) % 256
        elif cmd == '-':
            tape[dp] = (tape[dp] - 1) % 256
        elif cmd == '.':
            ch = chr(tape[dp])
            line_buffer.append(ch)
            if ch == '\n':
                # In raw mode, we need \r\n (carriage return + newline) for proper terminal output
                if shared['raw'] and line_buffer and line_buffer[-1] == '\n':
                    line_buffer[-1] = '\r\n'
                flush_buffer()
        elif cmd == ',':
            flush_buffer()
            if shared['raw']:
                # Raw mode: buffer a full line before feeding characters to the BF program
                # This ensures backspace works correctly — characters are only sent after Enter
                if input_buffer:
                    tape[dp] = input_buffer.pop(0)
                else:
                    # Read keystrokes until Enter, building the input buffer
                    while not disconnect.is_set():
                        byte = os.read(sys.stdin.fileno(), 1)
                        if not byte:
                            disconnect.set()
                            return
                        b = byte[0]

                        # Ctrl+C: exit cleanly
                        if b == 3:
                            disconnect.set()
                            return

                        # Enter key: raw mode sends \r (13), BF expects \n (10)
                        if b == 13:
                            input_buffer.append(10)
                            with print_lock:
                                sys.stdout.write('\r\n')
                                sys.stdout.flush()
                                shared['input'] = ''
                            break

                        # Backspace (127) or Delete (8): remove from buffer, not sent
                        if b == 127 or b == 8:
                            with print_lock:
                                if shared['input']:
                                    shared['input'] = shared['input'][:-1]
                                    sys.stdout.write('\b \b')
                                    sys.stdout.flush()
                            continue

                        # Regular character: add to buffer and echo
                        input_buffer.append(b)
                        ch = chr(b)
                        with print_lock:
                            shared['input'] += ch
                            sys.stdout.write(ch)
                            sys.stdout.flush()

                    # If disconnect happened before any input, exit
                    if not input_buffer:
                        disconnect.set()
                        return
                    tape[dp] = input_buffer.pop(0)
            else:
                # Normal mode: standard stdin read
                ch = sys.stdin.read(1)
                if not ch:
                    disconnect.set()
                    return
                tape[dp] = ord(ch)
        elif cmd == '[':
            if tape[dp] == 0:
                ip = jumps[ip]
        elif cmd == ']':
            if tape[dp] != 0:
                ip = jumps[ip]
        elif cmd == '~':
            if conn is None:
                return
            try:
                data = conn.recv(1)
                if not data:
                    disconnect.set()
                    return
                tape[dp] = data[0]
            except (OSError, ConnectionError):
                disconnect.set()
                return
        elif cmd == '^':
            if conn is None:
                return
            try:
                conn.send(bytes([tape[dp]]))
            except (BrokenPipeError, ConnectionResetError, OSError):
                disconnect.set()
                return

        ip += 1

    # Flush any remaining buffered output
    flush_buffer()


def _execute_sequential(program, jumps, args):
    """Execute a BF program sequentially (no threading). Used for standard BF programs."""
    tape = [0] * TAPE_SIZE
    dp = 0
    ip = 0
    conn = None

    while ip < len(program):
        cmd = program[ip]

        if cmd == '>':
            dp += 1
            if dp >= TAPE_SIZE:
                print("Error: Data pointer moved past end of tape.", file=sys.stderr)
                sys.exit(1)
        elif cmd == '<':
            dp -= 1
            if dp < 0:
                print("Error: Data pointer moved before start of tape.", file=sys.stderr)
                sys.exit(1)
        elif cmd == '+':
            tape[dp] = (tape[dp] + 1) % 256
        elif cmd == '-':
            tape[dp] = (tape[dp] - 1) % 256
        elif cmd == '.':
            sys.stdout.write(chr(tape[dp]))
            sys.stdout.flush()
        elif cmd == ',':
            ch = sys.stdin.read(1)
            tape[dp] = ord(ch) if ch else 0
        elif cmd == '[':
            if tape[dp] == 0:
                ip = jumps[ip]
        elif cmd == ']':
            if tape[dp] != 0:
                ip = jumps[ip]
        elif cmd == '@':
            conn = open_socket(args)
        elif cmd == '~':
            if conn is None:
                print("Error: ~ (recv) called with no open socket.", file=sys.stderr)
                sys.exit(1)
            data = conn.recv(1)
            if not data:
                print("\nConnection closed.")
                sys.exit(0)
            tape[dp] = data[0]
        elif cmd == '^':
            if conn is None:
                print("Error: ^ (send) called with no open socket.", file=sys.stderr)
                sys.exit(1)
            try:
                conn.send(bytes([tape[dp]]))
            except (BrokenPipeError, ConnectionResetError):
                print("\nConnection closed.")
                sys.exit(0)
        elif cmd == '!':
            if conn is not None:
                print("Goodbye!")
                conn.close()
                conn = None

        ip += 1


def execute(program, jumps, args):
    """Execute the BF program. If '#' is found, split into concurrent threads."""

    # Check if the program contains '#' (fork command)
    try:
        fork_pos = program.index('#')
    except ValueError:
        fork_pos = -1

    if fork_pos == -1:
        # No fork: run the entire program sequentially (standard BF mode)
        _execute_sequential(program, jumps, args)
        return

    # Fork mode: run '@' to open the socket, then split into two threads
    conn = None

    # Find and execute '@' before the fork
    for i in range(fork_pos):
        if program[i] == '@':
            conn = open_socket(args)
            break

    if conn is None and (args.server or args.client):
        print("Error: No @ command found before #.", file=sys.stderr)
        sys.exit(1)

    # Section A: everything between '@' and '#' (the receive section)
    at_pos = program.index('@') if '@' in program[:fork_pos] else -1
    section_a = program[at_pos + 1:fork_pos]

    # Section B: everything after '#' up to '!' (the send section)
    remaining = program[fork_pos + 1:]
    if remaining and remaining[-1] == '!':
        section_b = remaining[:-1]
    else:
        section_b = remaining

    disconnect = threading.Event()
    print_lock = threading.Lock()

    # Shared state between threads
    shared = {'input': '', 'raw': False}

    # Enable raw terminal mode so the interpreter controls keystroke echo
    # This prevents incoming messages from interleaving with typed text
    use_raw = sys.stdin.isatty()
    fd = None
    old_settings = None
    if use_raw:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
        shared['raw'] = True

    try:
        t1 = threading.Thread(
            target=run_section,
            args=(section_a, conn, disconnect, print_lock, "recv", shared),
            daemon=True,
        )
        t2 = threading.Thread(
            target=run_section,
            args=(section_b, conn, disconnect, print_lock, "send", shared),
            daemon=True,
        )

        t1.start()
        t2.start()

        # Wait for either thread to finish or Ctrl+C
        clean_quit = False
        try:
            while t1.is_alive() and t2.is_alive():
                t1.join(timeout=0.1)
            # If send thread exited without disconnect, it's a clean quit
            if not t2.is_alive() and not disconnect.is_set():
                clean_quit = True
        except KeyboardInterrupt:
            pass

        # Signal both threads to stop and close the socket
        disconnect.set()
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

        t1.join(timeout=1)
        t2.join(timeout=1)

    finally:
        # Restore terminal to normal mode before printing exit messages
        if use_raw and old_settings is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Print exit message after terminal is restored
    print("\nGoodbye!" if clean_quit else "\nConnection closed.")


def main():
    args = parse_args()
    program = load_program(args.program)
    jumps = precompute_brackets(program)
    execute(program, jumps, args)


if __name__ == '__main__':
    main()
