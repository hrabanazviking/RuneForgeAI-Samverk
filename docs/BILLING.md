# Billing — there is none (S-202)

Samverk has no billing. This page exists because people
arriving from hosted forges look for billing — a plan, a
seat count, a payment method — and in Samverk they should
find the answer where they look, stated plainly, instead
of wondering whether they missed the menu.

## What does not exist

- No seats. People are never counted as units.
- No plans and no tiers. There is nothing to upgrade to.
- No invoices, no charges, no payment methods. Samverk
  never asks for a card, and no code in it can take one.
- No free tier and no trial — those are shapes of billing
  too, and there is no billing here for them to be shapes
  of.

This is not a policy that could change with a settings
toggle. There is no billing table, no billing column and
no billing event anywhere in Samverk; the billing page in
an organization's settings (`samverk/billing_hole.py`)
inspects the live instance and reports the emptiness it
actually finds, and its battery plants a billing-shaped
table to prove the inspection would catch one.

## Why

Samverk is free software under the AGPL-3.0. The licence
grants use, study, sharing and change for no fee, to
everyone, forever — charging for Samverk itself would
contradict the terms it is given under.

It also runs on your own machines. A hosted forge bills
because it owns the computers, the disks and the
bandwidth and rents them back by the seat. A Samverk
instance owns nothing: the computer, the disk and the
electricity already belong to the people running it, so
there is no service to meter and no host to pay.

And membership is a relationship, not inventory. An
organization's first member and its ten-thousandth cost
the same — nothing — because there is no meter running.
To add people, add members. No seat is needed, because
there are no seats.

One nearby word is not billing: a repository *quota* is
a disk budget on a machine its owner owns. It exists so
an instance cannot fill its own disk by accident. It
charges nobody anything; it only guards capacity that
was already yours.

## If you came here to pay

There is nobody to pay and nothing to pay for. If you
want to support free software, the AGPL's own answer is
the honest one: use it, share it, and pass the source
along with it.
