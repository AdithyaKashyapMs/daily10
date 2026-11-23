"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Snappy, { type SnappyPose } from "@/components/Snappy";
import { getCode, getFaculty } from "@/lib/session";

const SCENES: { pose: SnappyPose; block: string; step: string; title: string; text: string }[] = [
  {
    pose: "papers",
    block: "block-sky",
    step: "1",
    title: "Your college uploads the syllabus",
    text: "Faculty add the notes and past papers once. They're split into small daily topics, with questions checked against the notes.",
  },
  {
    pose: "book",
    block: "block-tomato",
    step: "2",
    title: "You study 10 minutes a day",
    text: "One short topic, five quick questions and one past exam question. A reminder arrives at the time you pick.",
  },
  {
    pose: "celebrate",
    block: "block-mint",
    step: "3",
    title: "Exams come, no panic",
    text: "By exam day you've seen every topic, and the ones you got wrong came back until they stuck.",
  },
];

const FEATURES: { pose: SnappyPose; title: string; text: string; tint: string }[] = [
  {
    pose: "shield",
    title: "From your own notes",
    text: "Every question quotes the page it came from, and faculty approve it before you see it.",
    tint: "bg-mint-soft",
  },
  {
    pose: "search",
    title: "Comes back before you forget",
    text: "Got it wrong? It's back tomorrow. Got it right? You'll see it in 2, then 4, then 8 days.",
    tint: "bg-sky-soft",
  },
  {
    pose: "fire",
    title: "Missed a day? That's fine",
    text: "Your plan spreads the backlog over the coming days instead of doubling tomorrow.",
    tint: "bg-sun-soft",
  },
];

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    // Signed-in users go straight to their own home.
    if (getFaculty()) router.replace("/faculty");
    else if (getCode()) router.replace("/today");
  }, [router]);

  return (
    <div>
      <section className="block-sun border-b-[2.5px] border-ink">
        <div className="mx-auto grid max-w-6xl items-center gap-8 px-4 py-12 sm:px-6 md:grid-cols-[1.2fr_1fr] md:py-20">
          <div>
            <span className="chip mb-5">For every semester · every subject · every student</span>
            <h1 className="font-display text-5xl font-extrabold leading-[1.05] sm:text-6xl">
              Ten minutes a day.
              <br />
              No exam panic.
            </h1>
            <p className="mt-5 max-w-xl text-lg font-semibold text-ink/80">
              Most of us study in the last five days before an exam. Daily 10 spreads your whole syllabus across the
              semester, in ten-minute sessions built from your own college notes and past papers.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/auth/student" className="btn btn-primary btn-lg">I&apos;m a student</Link>
              <Link href="/auth/faculty" className="btn btn-white btn-lg">I&apos;m faculty</Link>
            </div>
          </div>
          <div className="relative flex justify-center md:justify-end">
            <div className="bubble absolute left-2 top-0 hidden sm:block md:left-6">Just 10 minutes? Easy!</div>
            <Snappy pose="book" size={250} className="mt-14" />
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <h2 className="font-display text-4xl font-extrabold">How it works</h2>
        <p className="mt-2 text-lg font-semibold text-ink-soft">Three scenes. No all-nighters.</p>
        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {SCENES.map((scene) => (
            <article key={scene.step} className="sticker-lg overflow-hidden">
              <div className={`${scene.block} relative flex justify-center border-b-[3px] border-ink pb-2 pt-6`}>
                <span className="absolute left-4 top-4 flex h-10 w-10 items-center justify-center rounded-full border-[2.5px] border-ink bg-white font-display text-xl font-extrabold text-ink">
                  {scene.step}
                </span>
                <Snappy pose={scene.pose} size={150} />
              </div>
              <div className="p-5">
                <h3 className="font-display text-2xl font-extrabold">{scene.title}</h3>
                <p className="mt-2 font-semibold text-ink-soft">{scene.text}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="border-y-[2.5px] border-ink bg-white">
        <div className="mx-auto grid max-w-6xl gap-6 px-4 py-14 sm:px-6 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className={`sticker flex items-center gap-4 p-4 ${f.tint}`}>
              <Snappy pose={f.pose} size={92} bob={false} className="shrink-0" />
              <div>
                <h3 className="font-display text-xl font-extrabold">{f.title}</h3>
                <p className="mt-1 text-sm font-semibold text-ink-soft">{f.text}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="block-plum border-b-[2.5px] border-ink">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-4 py-14 text-center sm:px-6 md:flex-row md:text-left">
          <div className="flex -space-x-6">
            <Snappy pose="papers" size={110} />
            <Snappy pose="pencil" size={110} className="[animation-delay:0.4s]" />
            <Snappy pose="celebrate" size={110} className="[animation-delay:0.8s]" />
          </div>
          <div className="flex-1">
            <h2 className="font-display text-4xl font-extrabold">Teaching a subject?</h2>
            <p className="mt-2 text-lg font-semibold text-white/90">
              Upload your notes and past papers once. Review the questions. Every student in your class gets a plan.
            </p>
          </div>
          <Link href="/auth/faculty" className="btn btn-sun btn-lg">Faculty login</Link>
        </div>
      </section>

      <footer className="mx-auto max-w-6xl px-4 py-8 text-sm font-semibold text-ink-soft sm:px-6">
        Daily 10 · built on the same stack and look as EventSnap.
      </footer>
    </div>
  );
}
