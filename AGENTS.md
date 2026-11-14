# Notes for AI coding agents

This repo is TapJob: a Vexo Open band that turns spoken job notes into a Stripe invoice.
Read `README.md` first, then `vexo-open-kit/AGENTS.md` for the band's own rules.

## Before you change anything

- Run `python3 -m unittest discover -s tests -v`. All eight must pass before and after.
- Try the loop without hardware: `python3 app.py --sim --demo`.
- Ask the team for their band number. Never guess it, never connect to another band.

## Rules

- **Keys live in `.env` only.** Never print a key, never write one into code, a commit, a
  page or a chat. `.env`, `jobs/` and `vexo-open-kit/` are in `.gitignore`: keep them there.
- **Do not edit `vexo-open-kit/`.** It is the organisers' kit, cloned as it is.
- **Stripe test mode only.** `billing.py` refuses live keys on purpose. Leave that check in.
- **The model never does the sums.** Prices times quantities, labor and totals stay in
  `brain.make_draft`. The model only fills the fields in `GEMINI_SCHEMA`.
- **Standard library only**, plus `bleak` for Bluetooth. Do not add packages on demo day.
- **Handlers stay short.** A function given to `band.on(...)` only puts a note in
  `hub.inbox`; the main loop in `Hub.run` does the work. Never call a network service from
  a handler.
- **Light or microphone, not both.** While `audio` is on the band refuses LED commands.
  `Hub.led` swallows that refusal; set the light after `configure(audio=False)`.
- **One program per band.** Close the kit's dashboard tab before `python3 app.py N`, and
  double-tap the band before every connect.

## Where things are

| To change | Look in |
|---|---|
| What a double-tap does in each phase | `Hub.tap` in `app.py` |
| The prompt and the fields the model returns | `INSTRUCTIONS`, `GEMINI_SCHEMA` in `brain.py` |
| Labor rounding, warnings, totals | `brain.make_draft` |
| What is sent to Stripe | `StripeBilling.create_invoice` in `billing.py` |
| The read-back sentence | `brain.read_back` |
| The page | `static/index.html` (it polls `/state`, posts to `/action`) |

## Likely first problems with a real band

- `Could not see Vexo-HACK-N`: something else is connected (dashboard tab, another
  program), or the band was not double-tapped in the last 60 seconds.
- No words appear: `DEEPGRAM_API_KEY` missing in `.env`, or no internet. The terminal says which.
- The job stops by itself while working: raise `tap_threshold_g` in `config.json`.
- macOS asks for Bluetooth permission for the terminal the first time: allow it, run again.
