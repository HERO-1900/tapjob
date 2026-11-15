# TapJob — text for the Devpost page

**Tagline:** Say it. Get paid. Every job has a hero.

## Inspiration

People who work with their hands owe someone a bill at the end of every job: the plumber under
the sink, the crew at a drive-through window, a massage therapist, a mechanic. The bill gets
written later, from memory, on a phone or a register their hands were too busy to touch. A
band on the wrist is the one computer that is there while the work happens.

You did the job at 2. You billed it at 11 p.m. Or never. Paperwork is a second shift nobody
pays for, and by then half of it is forgotten. This is not a niche: the US Bureau of Labor
Statistics counts about 3.9 million fast food and counter workers, 2.1 million waiters and
waitresses, 806,000 auto mechanics, 575,000 hairstylists, 505,000 plumbers and pipefitters and
100,000 gas station and car service attendants. Close to 8 million people in six jobs alone,
before boba shops, food trucks, movers, cleaners and farmers markets.

## What it does

1. **Double-tap the Vexo band.** It listens while you work. Its light is blue, so the people
   near you can see the microphone is on.
2. **Say what you did or what was ordered.** "Two double cheeseburgers, one fries, a diet soda
   and a shake." No prices.
3. **Double-tap again.** The words become a ticket. Every price comes from the wearer's own
   price list, looked up in plain code and marked on the ticket. For jobs that bill by the
   hour, hours you did not say are timed by the band.
4. **The ticket is read back. Raise your fist for a second, or double-tap, to send it.** A
   Stripe invoice with a payment page and a QR code.
5. **The customer pays. The band turns green.**

Every job has a hero card: plumber, drive-through order taker, massage therapist, mechanic.
Not there? Describe your job in one sentence and Gemini writes the card, a starter price list
and paints the hero. Paste or upload your own menu at any time.

**The dashboard.** A bill that is still unpaid does not block you: double-tap (or press New
job) and take the next one. Every bill that went out is on the dashboard as Waiting, Paid or
Taken back, with the totals, and an earlier bill turns to Paid by itself when the customer
pays. Discard after sending voids the invoice at Stripe.

**Try it without a band.** The project page runs the same loop on a pretend band in your
browser, from the words to PAID: http://tapjob.ipolab.ai/#live

## How we built it

- **Vexo Open band**: double-tap and orientation events, the Opus microphone stream, the
  activity stream and the LED, over the USB cable or Bluetooth, through the organisers' kit.
- **Deepgram**: live speech-to-text while the job runs, and the voice that reads the ticket back.
- **Gemini 4**: structured output for three things (spoken words to ticket fields, one sentence
  to a job card, a pasted menu to a price list) and the image model for the hero pictures.
- **Stripe** (test mode): customer, invoice items, invoice, hosted payment page; the app polls
  until the invoice is paid.
- A small Python state machine in between (standard library, plus `bleak` and `pyserial`),
  and one web page on localhost.

Rule we kept: **the model never sets a price and never does arithmetic.** It only matches
words to names. Prices, quantities and totals are computed in code, so every number on the
ticket can be traced to the price list or to something that was said out loud.

## Challenges we ran into

- The band takes one connection at a time, and its light is locked while the microphone is on,
  so the feedback had to be designed around that.
- The laptop's own voice, playing next to the band, shook it into double-taps and sent a draft
  by itself. Taps are now ignored while the computer is speaking.
- Stripe will not make a payment page for an invoice whose customer has no email.
- Keeping a language model away from the money.

## Accomplishments that we're proud of

The whole loop ran on a real band the same afternoon, over the cable and then over Bluetooth:
spoken order, priced ticket, raised fist, Stripe invoice, payment, PAID. Then a second job, a third, and one made from a sentence.

## What we learned

A tap is a timestamp, and the value of a wearable is capture during the work, not after it.
One bit of feedback is enough if it is the right bit: "did they pay?"

## What's next for TapJob

A phone app (the web cannot reach Bluetooth on an iPhone), branded shells for the band, the
pay code on a badge or a small screen, bigger catalogues, noisy kitchens, and the tools small
businesses already keep their books in.

## Built with

python, vexo-open-kit, deepgram, gemini, stripe, bleak, pyserial, html, css, javascript

## Tracks

Stripe: Best Economic Agent. Google DeepMind: Best Use of Gemini 4.

## Links

Code: https://github.com/HERO-1900/tapjob
Project page: http://tapjob.ipolab.ai
