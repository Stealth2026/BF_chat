===============================================================================
BRAINFUCK CHAT
===============================================================================

A concurrent chat program written entirely in Brainfuck

Both the server and the client run this same program  The interpreter handles
the connection setup based on command line flags  The BF application logic is
identical for both sides

The program has two halves separated by the fork command

  First half   receive messages from the network and display them
  Second half  read messages from the keyboard and send them over the network

Both halves run simultaneously in separate threads  Each thread gets its own
memory tape  They share the TCP socket connection

Protocol  a single newline marks the end of each message

===============================================================================
MEMORY TAPE LAYOUT (per thread)
===============================================================================

Cell 0  WORK CELL       the byte currently being read or sent
Cell 1  LOOP FLAG       1 means keep running  0 means exit the loop
Cell 2  SEND NL FLAG    used in the send thread to decide whether to send the
                        newline after the inner loop  1 means send it  0 means
                        skip it (quit case)
Cell 3  SCRATCH COUNTER loop counter for ASCII multiplication during label
                        construction (receive thread only)
Cell 4  ACCUMULATOR     accumulates the product during ASCII multiplication
                        (receive thread only)  In the send thread this cell
                        serves as the quit flag  it starts at 1 each turn and
                        is zeroed when a real byte is sent

===============================================================================
SETUP
===============================================================================

Open TCP socket (the interpreter handles server vs client based on flags)

@

===============================================================================
RECEIVE THREAD
===============================================================================

This section runs in its own thread after the fork command  It loops forever
and prints the label before each incoming message then reads bytes from the
network and displays them until a newline arrives

Set cell 1 to 1 (loop flag) and enter the outer loop

>+

[

Move to cell 0 (home position) to begin this iteration

<

===============================================================================
PRINT "Remote: " LABEL
===============================================================================

Each character is built using an ASCII multiplication loop  The pattern is
move to cell 3 and set a counter then multiply into cell 4 and add a
remainder then print the result then zero both cells and return to cell 0

Print 'R' (ASCII 82 = 8 x 10 then add 2)

>>>++++++++[>++++++++++<-]>++.[-]<[-]<<<

Print 'e' (ASCII 101 = 10 x 10 then add 1)

>>>++++++++++[>++++++++++<-]>+.[-]<[-]<<<

Print 'm' (ASCII 109 = 10 x 10 then add 9)

>>>++++++++++[>++++++++++<-]>+++++++++.[-]<[-]<<<

Print 'o' (ASCII 111 = 10 x 11 then add 1)

>>>++++++++++[>+++++++++++<-]>+.[-]<[-]<<<

Print 't' (ASCII 116 = 11 x 10 then add 6)

>>>+++++++++++[>++++++++++<-]>++++++.[-]<[-]<<<

Print 'e' (ASCII 101 = 10 x 10 then add 1)

>>>++++++++++[>++++++++++<-]>+.[-]<[-]<<<

Print ':' (ASCII 58 = 5 x 10 then add 8)

>>>+++++[>++++++++++<-]>++++++++.[-]<[-]<<<

Print ' ' (ASCII 32 = 8 x 4)

>>>++++++++[>++++<-]>.[-]<[-]<<<

===============================================================================
RECEIVE ONE MESSAGE
===============================================================================

Read a byte from the network and subtract 10 to test for newline (ASCII 10)
If nonzero (not a newline) restore it and print it and read the next byte
Repeat until a newline is found then restore and print the newline

~----------[++++++++++.~----------]++++++++++.

Move to cell 1 (still 1) and loop back for the next message

>

]

===============================================================================
FORK
===============================================================================

Everything above this line becomes the receive thread
Everything below this line becomes the send thread
Each thread gets its own memory tape  Both share the TCP socket

#

===============================================================================
SEND THREAD
===============================================================================

This section runs in its own thread after the fork  It reads bytes from the
keyboard and sends them over the network  The terminal echoes what the user
types so no label is needed  Only incoming messages need a label to
distinguish them

If the user presses Enter without typing anything the quit flag in cell 4
stays at 1  The quit check detects this and zeros cell 1 which causes the
loop to exit  When the turn is empty the newline is NOT sent over the
network so the other side does not see a blank message

Set cell 1 to 1 (loop flag) and enter the outer loop

>+

[

Move to cell 0 (home position)

<

===============================================================================
SET QUIT FLAG
===============================================================================

Move to cell 4 and set it to 1  This flag assumes the turn is empty (quit)
until proven otherwise  If any real byte is sent during this turn cell 4
is zeroed

>>>>+<<<<

===============================================================================
SEND ONE MESSAGE
===============================================================================

Read a byte from the keyboard and subtract 10 to test for newline
If nonzero  restore the byte and send it over the network and zero cell 4
(this turn has real content) then read the next byte and subtract 10
Repeat until a newline is found

,----------[++++++++++^>>>>[-]<<<<,----------]

===============================================================================
CONDITIONAL NEWLINE SEND AND QUIT CHECK
===============================================================================

At this point cell 0 is 0 (the newline was detected by subtracting 10)
Cell 4 is either 0 (real bytes were sent = normal message) or 1 (empty
turn = quit signal)

Set cell 2 to 1  This flag means "send the newline"  It will be zeroed
by the quit check if the turn was empty

>>+

Move to cell 4 to check the quit flag

>>

If cell 4 is 1 (empty turn = quit)  zero cell 4 then zero cell 2 (do
not send the newline) then zero cell 1 (exit the outer loop) then
return to cell 4

[[-]<<[-]<[-]>>>]

Move to cell 2 to check the send flag

<<

If cell 2 is 1 (normal message  not quit)  zero cell 2 then move to
cell 0 and restore the newline (add 10 back) and send it over the
network then return to cell 2

[[-]<<++++++++++^>>]

Return to cell 0

<<

Move to cell 1 for the outer loop check

>

]

===============================================================================
CLOSE
===============================================================================

Close the socket and clean up

!
