---
source: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
fetched: 2026-08-22
mode: html
---

<div id="main-content" role="main">

<div class="section page-wrapper HeroEngineering-module-scss-module__j1ivRa__hero" aria-label="Engineering Article Hero">

<a href="/engineering" class="body-2 bold HeroEngineering-module-scss-module__j1ivRa__hubLink">Engineering at Anthropic</a>

<div class="HeroEngineering-module-scss-module__j1ivRa__content">

<div class="HeroEngineering-module-scss-module__j1ivRa__header">

<div class="HeroEngineering-module-scss-module__j1ivRa__heroImage">

<img src="https://www-cdn.anthropic.com/images/4zrzovbb/website/5dfb835ad3cbbf76b85824e969146eac20329e72-1000x1000.svg" style="color:transparent" loading="lazy" decoding="async" data-nimg="1" width="1000" height="1000" />

</div>

# Effective harnesses for long-running agents

</div>

<div class="HeroEngineering-module-scss-module__j1ivRa__metadata">

Published Nov 26, 2025

Agents still face challenges working across many context windows. We looked to human engineers for inspiration in creating a more effective harness for long-running agents.

</div>

</div>

</div>

<div class="page-wrapper">

<div>

<div class="Body-module-scss-module__z40yvW__body" data-theme="ivory">

As AI agents become more capable, developers are increasingly asking them to take on complex tasks requiring work that spans hours, or even days. However, getting agents to make consistent progress across multiple context windows remains an open problem.

The core challenge of long-running agents is that they must work in discrete sessions, and each new session begins with no memory of what came before. Imagine a software project staffed by engineers working in shifts, where each new engineer arrives with no memory of what happened on the previous shift. Because context windows are limited, and because most complex projects cannot be completed within a single window, agents need a way to bridge the gap between coding sessions.

We developed a two-fold solution to enable the [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) to work effectively across many context windows: an **initializer agent** that sets up the environment on the first run, and a **coding agent** that is tasked with making incremental progress in every session, while leaving clear artifacts for the next session. You can find code examples in the accompanying [quickstart.](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding)

## The long-running agent problem

The Claude Agent SDK is a powerful, general-purpose agent harness adept at coding, as well as other tasks that require the model to use tools to gather context, plan, and execute. It has context management capabilities such as compaction, which enables an agent to work on a task without exhausting the context window. Theoretically, given this setup, it should be possible for an agent to continue to do useful work for an arbitrarily long time.

However, compaction isn’t sufficient. Out of the box, even a frontier coding model like Opus 4.5 running on the Claude Agent SDK in a loop across multiple context windows will fall short of building a production-quality web app if it’s only given a high-level prompt, such as “build a clone of [claude.ai](http://claude.ai/redirect/website.v1.ca08e656-3dae-433c-938e-d57e32f6ab4b).”

Claude’s failures manifested in two patterns. First, the agent tended to try to do too much at once—essentially to attempt to one-shot the app. Often, this led to the model running out of context in the middle of its implementation, leaving the next session to start with a feature half-implemented and undocumented. The agent would then have to guess at what had happened, and spend substantial time trying to get the basic app working again. This happens even with compaction, which doesn’t always pass perfectly clear instructions to the next agent.

A second failure mode would often occur later in a project. After some features had already been built, a later agent instance would look around, see that progress had been made, and declare the job done.

This decomposes the problem into two parts. First, we need to set up an initial environment that lays the foundation for *all* the features that a given prompt requires, which sets up the agent to work step-by-step and feature-by-feature. Second, we should prompt each agent to make incremental progress towards its goal while also leaving the environment in a clean state at the end of a session. By “clean state” we mean the kind of code that would be appropriate for merging to a main branch: there are no major bugs, the code is orderly and well-documented, and in general, a developer could easily begin work on a new feature without first having to clean up an unrelated mess.

When experimenting internally, we addressed these problems using a two-part solution:

1.  Initializer agent: The very first agent session uses a specialized prompt that asks the model to set up the initial environment: an `init.sh` script, a claude-progress.txt file that keeps a log of what agents have done, and an initial git commit that shows what files were added.
2.  Coding agent: Every subsequent session asks the model to make incremental progress, then leave structured updates.<sup>1</sup>

The key insight here was finding a way for agents to quickly understand the state of work when starting with a fresh context window, which is accomplished with the claude-progress.txt file alongside the git history. Inspiration for these practices came from knowing what effective software engineers do every day.

## Environment management

In the updated [Claude 4 prompting guide](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices#multi-context-window-workflows), we shared some best practices for multi-context window workflows, including a harness structure that uses “a different prompt for the very first context window.” This “different prompt” requests that the initializer agent set up the environment with all the necessary context that future coding agents will need to work effectively. Here, we provide a deeper dive on some of the key components of such an environment.

### Feature list

To address the problem of the agent one-shotting an app or prematurely considering the project complete, we prompted the initializer agent to write a comprehensive file of feature requirements expanding on the user’s initial prompt. In the [claude.ai](http://claude.ai/redirect/website.v1.ca08e656-3dae-433c-938e-d57e32f6ab4b) clone example, this meant over 200 features, such as “a user can open a new chat, type in a query, press enter, and see an AI response.” These features were all initially marked as “failing” so that later coding agents would have a clear outline of what full functionality looked like.

<div class="Body-module-scss-module__z40yvW__media-column Body-module-scss-module__z40yvW__inline">

<div class="CodeBlock-module-scss-module__PbWBnq__codeBlock">

```
{
    "category": "functional",
    "description": "New chat button creates a fresh conversation",
    "steps": [
      "Navigate to main interface",
      "Click the 'New Chat' button",
      "Verify a new conversation is created",
      "Check that chat area shows welcome state",
      "Verify conversation appears in sidebar"
    ],
    "passes": false
  }
```

<div class="CodeBlock-module-scss-module__PbWBnq__controls">

<img src="data:image/svg+xml;base64,PHN2ZyBjbGFzcz0iSWNvbi1tb2R1bGUtc2Nzcy1tb2R1bGVfX2xxYmRIR19faWNvbiIgd2lkdGg9IjExIiBoZWlnaHQ9IjE1IiB2aWV3Ym94PSIwIDAgMTEgMTUiPjxwYXRoIGQ9Ik01LjQgMEM2LjM5ODc1IDAgNy4yNjgxOSAwLjU0MzgxNCA3LjczNTI1IDEuMzVIOS40NUMxMC4xOTU2IDEuMzUgMTAuOCAxLjk1NDQyIDEwLjggMi43VjEzLjVDMTAuOCAxNC4yNDU2IDEwLjE5NTYgMTQuODUgOS40NSAxNC44NUgxLjM1QzAuNjA0NDE1IDE0Ljg1IDIuMTc0MzZlLTA4IDE0LjI0NTYgMCAxMy41VjIuN0MxLjczOTVlLTA3IDEuOTU0NDIgMC42MDQ0MTUgMS4zNSAxLjM1IDEuMzVIMy4wNjQ3NUMzLjUzMTgxIDAuNTQzODE0IDQuNDAxMjUgMCA1LjQgMFpNMS4zNSAyLjI1QzEuMTAxNDcgMi4yNSAwLjkgMi40NTE0NyAwLjkgMi43VjEzLjVDMC45IDEzLjc0ODUgMS4xMDE0NyAxMy45NSAxLjM1IDEzLjk1SDkuNDVDOS42OTg1MyAxMy45NSA5LjkgMTMuNzQ4NSA5LjkgMTMuNVYyLjdDOS45IDIuNDUxNDcgOS42OTg1MyAyLjI1IDkuNDUgMi4yNUg4LjA2MjIxQzguMDg2NzcgMi4zOTYzNyA4LjEgMi41NDY2NSA4LjEgMi43VjMuNkM4LjEgMy44NDg1MyA3Ljg5ODUzIDQuMDUgNy42NSA0LjA1SDMuMTVDMi45MDE0NyA0LjA1IDIuNyAzLjg0ODUzIDIuNyAzLjZWMi43QzIuNyAyLjU0NjY1IDIuNzEzMjMgMi4zOTYzNyAyLjczNzc5IDIuMjVIMS4zNVpNNy42ODYwMyAxMC42MjMzQzcuNzgzNzYgMTAuMzk1IDguMDQ4MjggMTAuMjg4NiA4LjI3NjY2IDEwLjM4NkM4LjUwNDk5IDEwLjQ4MzggOC42MTE0MyAxMC43NDgzIDguNTEzOTYgMTAuOTc2N0M4LjI0ODU2IDExLjU5NjcgNy43MzAxNCAxMi4xNSA3LjAxOTgyIDEyLjE1QzYuNTgxOTIgMTIuMTQ5OSA2LjIxNzIyIDExLjkzOTcgNS45Mzk2NSAxMS42MzMyQzUuNjYyMTUgMTEuOTM5NSA1LjI5ODAxIDEyLjE0OTkgNC44NjAzNSAxMi4xNUM0LjQyMjI5IDEyLjE1IDQuMDU2OTIgMTEuOTM5OCAzLjc3OTMgMTEuNjMzMkMzLjUwMTc1IDExLjkzOTUgMy4xMzc3MyAxMi4xNSAyLjcgMTIuMTVDMi40NTE0NyAxMi4xNSAyLjI1IDExLjk0ODUgMi4yNSAxMS43QzIuMjUgMTEuNDUxNSAyLjQ1MTQ3IDExLjI1IDIuNyAxMS4yNUMyLjg5MTIgMTEuMjUgMy4xNjcyNiAxMS4wODc5IDMuMzY2MjEgMTAuNjIzM0wzLjM5Njk3IDEwLjU2MzZDMy40NzgwNiAxMC40MzIxIDMuNjIyNjEgMTAuMzUgMy43ODAxOCAxMC4zNUMzLjk2MDIgMTAuMzUwMSA0LjEyMzMgMTAuNDU3OCA0LjE5NDE0IDEwLjYyMzNDNC4zOTMwOSAxMS4wODc4IDQuNjY5MTcgMTEuMjUgNC44NjAzNSAxMS4yNUM1LjA1MTU2IDExLjI0OTggNS4zMjc3MyAxMS4wODc3IDUuNTI2NTYgMTAuNjIzM0w1LjU1NzMyIDEwLjU2MzZDNS42MzgzNyAxMC40MzIzIDUuNzgyMjkgMTAuMzUwMSA1LjkzOTY1IDEwLjM1QzYuMTE5NzQgMTAuMzUgNi4yODI3NSAxMC40NTc4IDYuMzUzNjEgMTAuNjIzM0M2LjU1MjUxIDExLjA4NzggNi44Mjg2MiAxMS4yNDk5IDcuMDE5ODIgMTEuMjVDNy4yMTEwMiAxMS4yNSA3LjQ4NzA4IDExLjA4NzkgNy42ODYwMyAxMC42MjMzWk03LjY4NjAzIDcuMDIzMzRDNy43ODM3NiA2Ljc5NTAxIDguMDQ4MjggNi42ODg1NyA4LjI3NjY2IDYuNzg2MDRDOC41MDQ5OSA2Ljg4Mzc2IDguNjExNDMgNy4xNDgyOCA4LjUxMzk2IDcuMzc2NjZDOC4yNDg1NiA3Ljk5Njc1IDcuNzMwMTQgOC41NSA3LjAxOTgyIDguNTVDNi41ODE5MiA4LjU0OTk0IDYuMjE3MjIgOC4zMzk3IDUuOTM5NjUgOC4wMzMyQzUuNjYyMTUgOC4zMzk0NyA1LjI5ODAxIDguNTQ5ODkgNC44NjAzNSA4LjU1QzQuNDIyMjkgOC41NSA0LjA1NjkyIDguMzM5ODMgMy43NzkzIDguMDMzMkMzLjUwMTc1IDguMzM5NDUgMy4xMzc3MyA4LjU1IDIuNyA4LjU1QzIuNDUxNDcgOC41NSAyLjI1IDguMzQ4NTMgMi4yNSA4LjFDMi4yNSA3Ljg1MTQ3IDIuNDUxNDcgNy42NSAyLjcgNy42NUMyLjg5MTIgNy42NSAzLjE2NzI2IDcuNDg3OTEgMy4zNjYyMSA3LjAyMzM0TDMuMzk2OTcgNi45NjM1N0MzLjQ3ODA2IDYuODMyMTMgMy42MjI2MSA2Ljc1IDMuNzgwMTggNi43NUMzLjk2MDIgNi43NTAwNyA0LjEyMzMgNi44NTc4MyA0LjE5NDE0IDcuMDIzMzRDNC4zOTMwOSA3LjQ4NzgyIDQuNjY5MTcgNy42NSA0Ljg2MDM1IDcuNjVDNS4wNTE1NiA3LjY0OTggNS4zMjc3MyA3LjQ4NzcyIDUuNTI2NTYgNy4wMjMzNEw1LjU1NzMyIDYuOTYzNTdDNS42MzgzNyA2LjgzMjMyIDUuNzgyMjkgNi43NTAxMiA1LjkzOTY1IDYuNzVDNi4xMTk3NCA2Ljc1IDYuMjgyNzUgNi44NTc3OCA2LjM1MzYxIDcuMDIzMzRDNi41NTI1MSA3LjQ4NzgyIDYuODI4NjIgNy42NDk5IDcuMDE5ODIgNy42NUM3LjIxMTAyIDcuNjUgNy40ODcwOCA3LjQ4Nzg2IDcuNjg2MDMgNy4wMjMzNFpNNS40IDAuOUM0LjQwNTg5IDAuOSAzLjYgMS43MDU4OSAzLjYgMi43VjMuMTVINy4yVjIuN0M3LjIgMS43MDU4OSA2LjM5NDExIDAuOSA1LjQgMC45WiIgZmlsbD0iY3VycmVudENvbG9yIiAvPjwvc3ZnPg==" class="Icon-module-scss-module__lqbdHG__icon" /><span class="body-3">Copy</span>

</div>

</div>

</div>

We prompt coding agents to edit this file only by changing the status of a passes field, and we use strongly-worded instructions like “It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality.” After some experimentation, we landed on using JSON for this, as the model is less likely to inappropriately change or overwrite JSON files compared to Markdown files.

### Incremental progress

Given this initial environment scaffolding, the next iteration of the coding agent was then asked to work on only one feature at a time. This incremental approach turned out to be critical to addressing the agent’s tendency to do too much at once.

Once working incrementally, it’s still essential that the model leaves the environment in a clean state after making a code change. In our experiments, we found that the best way to elicit this behavior was to ask the model to commit its progress to git with descriptive commit messages and to write summaries of its progress in a progress file. This allowed the model to use git to revert bad code changes and recover working states of the code base.

These approaches also increased efficiency, as they eliminated the need for an agent to have to guess at what had happened and spend its time trying to get the basic app working again.

### Testing

One final major failure mode that we observed was Claude’s tendency to mark a feature as complete without proper testing. Absent explicit prompting, Claude tended to make code changes, and even do testing with unit tests or `curl` commands against a development server, but would fail recognize that the feature didn’t work end-to-end.

In the case of building a web app, Claude mostly did well at verifying features end-to-end once explicitly prompted to use browser automation tools and do all testing as a human user would.

<div class="Body-module-scss-module__z40yvW__media-column Body-module-scss-module__z40yvW__inline">

<figure class="ImageWithCaption-module-scss-module__Duq99q__e-imageWithCaption">
<img src="/_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2F4zrzovbb%2Fwebsite%2Ff94c2257964fb2d623f1e81f874977ebfc0986bc-1920x1080.gif&amp;w=3840&amp;q=75" style="color:transparent" loading="lazy" decoding="async" data-nimg="1" srcset="/_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2F4zrzovbb%2Fwebsite%2Ff94c2257964fb2d623f1e81f874977ebfc0986bc-1920x1080.gif&amp;w=1920&amp;q=75 1x, /_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2F4zrzovbb%2Fwebsite%2Ff94c2257964fb2d623f1e81f874977ebfc0986bc-1920x1080.gif&amp;w=3840&amp;q=75 2x" width="1920" height="1080" alt=" Screenshots taken by Claude through the Puppeteer MCP server as it tested the claude.ai clone. " />
<figcaption>Screenshots taken by Claude through the Puppeteer MCP server as it tested the claude.ai clone.<br />
</figcaption>
</figure>

</div>

Providing Claude with these kinds of testing tools dramatically improved performance, as the agent was able to identify and fix bugs that weren’t obvious from the code alone.

Some issues remain, like limitations to Claude’s vision and to browser automation tools making it difficult to identify every kind of bug. For example, Claude can’t see browser-native alert modals through the Puppeteer MCP, and features relying on these modals tended to be buggier as a result.

## Getting up to speed

With all of the above in place, every coding agent is prompted to run through a series of steps to get its bearings, some quite basic but still helpful:

1.  *Run `pwd` to see the directory you’re working in. You’ll only be able to edit files in this directory.*
2.  *Read the git logs and progress files to get up to speed on what was recently worked on.*
3.  *Read the features list file and choose the highest-priority feature that’s not yet done to work on.*

This approach saves Claude some tokens in every session since it doesn’t have to figure out how to test the code. It also helps to ask the initializer agent to write an init.sh script that can run the development server, and then run through a basic end-to-end test before implementing a new feature.

In the case of the claude.ai clone, this meant that the agent always started the local development server and used the Puppeteer MCP to start a new chat, send a message, and receive a response. This ensured that Claude could quickly identify if the app had been left in a broken state, and immediately fix any existing bugs. If the agent had instead started implementing a new feature, it would likely make the problem worse.

Given all this, a typical session starts off with the following assistant messages:

<div class="Body-module-scss-module__z40yvW__media-column Body-module-scss-module__z40yvW__inline">

<div class="CodeBlock-module-scss-module__PbWBnq__codeBlock">

```
[Assistant] I'll start by getting my bearings and understanding the current state of the project.
[Tool Use] <bash - pwd>
[Tool Use] <read - claude-progress.txt>
[Tool Use] <read - feature_list.json>
[Assistant] Let me check the git log to see recent work.
[Tool Use] <bash - git log --oneline -20>
[Assistant] Now let me check if there's an init.sh script to restart the servers.
<Starts the development server>
[Assistant] Excellent! Now let me navigate to the application and verify that some fundamental features are still working.
<Tests basic functionality>
[Assistant] Based on my verification testing, I can see that the fundamental functionality is working well. The core chat features, theme switching, conversation loading, and error handling are all functioning correctly. Now let me review the tests.json file more comprehensively to understand what needs to be implemented next.
<Starts work on a new feature>
```

<div class="CodeBlock-module-scss-module__PbWBnq__controls">

<img src="data:image/svg+xml;base64,PHN2ZyBjbGFzcz0iSWNvbi1tb2R1bGUtc2Nzcy1tb2R1bGVfX2xxYmRIR19faWNvbiIgd2lkdGg9IjExIiBoZWlnaHQ9IjE1IiB2aWV3Ym94PSIwIDAgMTEgMTUiPjxwYXRoIGQ9Ik01LjQgMEM2LjM5ODc1IDAgNy4yNjgxOSAwLjU0MzgxNCA3LjczNTI1IDEuMzVIOS40NUMxMC4xOTU2IDEuMzUgMTAuOCAxLjk1NDQyIDEwLjggMi43VjEzLjVDMTAuOCAxNC4yNDU2IDEwLjE5NTYgMTQuODUgOS40NSAxNC44NUgxLjM1QzAuNjA0NDE1IDE0Ljg1IDIuMTc0MzZlLTA4IDE0LjI0NTYgMCAxMy41VjIuN0MxLjczOTVlLTA3IDEuOTU0NDIgMC42MDQ0MTUgMS4zNSAxLjM1IDEuMzVIMy4wNjQ3NUMzLjUzMTgxIDAuNTQzODE0IDQuNDAxMjUgMCA1LjQgMFpNMS4zNSAyLjI1QzEuMTAxNDcgMi4yNSAwLjkgMi40NTE0NyAwLjkgMi43VjEzLjVDMC45IDEzLjc0ODUgMS4xMDE0NyAxMy45NSAxLjM1IDEzLjk1SDkuNDVDOS42OTg1MyAxMy45NSA5LjkgMTMuNzQ4NSA5LjkgMTMuNVYyLjdDOS45IDIuNDUxNDcgOS42OTg1MyAyLjI1IDkuNDUgMi4yNUg4LjA2MjIxQzguMDg2NzcgMi4zOTYzNyA4LjEgMi41NDY2NSA4LjEgMi43VjMuNkM4LjEgMy44NDg1MyA3Ljg5ODUzIDQuMDUgNy42NSA0LjA1SDMuMTVDMi45MDE0NyA0LjA1IDIuNyAzLjg0ODUzIDIuNyAzLjZWMi43QzIuNyAyLjU0NjY1IDIuNzEzMjMgMi4zOTYzNyAyLjczNzc5IDIuMjVIMS4zNVpNNy42ODYwMyAxMC42MjMzQzcuNzgzNzYgMTAuMzk1IDguMDQ4MjggMTAuMjg4NiA4LjI3NjY2IDEwLjM4NkM4LjUwNDk5IDEwLjQ4MzggOC42MTE0MyAxMC43NDgzIDguNTEzOTYgMTAuOTc2N0M4LjI0ODU2IDExLjU5NjcgNy43MzAxNCAxMi4xNSA3LjAxOTgyIDEyLjE1QzYuNTgxOTIgMTIuMTQ5OSA2LjIxNzIyIDExLjkzOTcgNS45Mzk2NSAxMS42MzMyQzUuNjYyMTUgMTEuOTM5NSA1LjI5ODAxIDEyLjE0OTkgNC44NjAzNSAxMi4xNUM0LjQyMjI5IDEyLjE1IDQuMDU2OTIgMTEuOTM5OCAzLjc3OTMgMTEuNjMzMkMzLjUwMTc1IDExLjkzOTUgMy4xMzc3MyAxMi4xNSAyLjcgMTIuMTVDMi40NTE0NyAxMi4xNSAyLjI1IDExLjk0ODUgMi4yNSAxMS43QzIuMjUgMTEuNDUxNSAyLjQ1MTQ3IDExLjI1IDIuNyAxMS4yNUMyLjg5MTIgMTEuMjUgMy4xNjcyNiAxMS4wODc5IDMuMzY2MjEgMTAuNjIzM0wzLjM5Njk3IDEwLjU2MzZDMy40NzgwNiAxMC40MzIxIDMuNjIyNjEgMTAuMzUgMy43ODAxOCAxMC4zNUMzLjk2MDIgMTAuMzUwMSA0LjEyMzMgMTAuNDU3OCA0LjE5NDE0IDEwLjYyMzNDNC4zOTMwOSAxMS4wODc4IDQuNjY5MTcgMTEuMjUgNC44NjAzNSAxMS4yNUM1LjA1MTU2IDExLjI0OTggNS4zMjc3MyAxMS4wODc3IDUuNTI2NTYgMTAuNjIzM0w1LjU1NzMyIDEwLjU2MzZDNS42MzgzNyAxMC40MzIzIDUuNzgyMjkgMTAuMzUwMSA1LjkzOTY1IDEwLjM1QzYuMTE5NzQgMTAuMzUgNi4yODI3NSAxMC40NTc4IDYuMzUzNjEgMTAuNjIzM0M2LjU1MjUxIDExLjA4NzggNi44Mjg2MiAxMS4yNDk5IDcuMDE5ODIgMTEuMjVDNy4yMTEwMiAxMS4yNSA3LjQ4NzA4IDExLjA4NzkgNy42ODYwMyAxMC42MjMzWk03LjY4NjAzIDcuMDIzMzRDNy43ODM3NiA2Ljc5NTAxIDguMDQ4MjggNi42ODg1NyA4LjI3NjY2IDYuNzg2MDRDOC41MDQ5OSA2Ljg4Mzc2IDguNjExNDMgNy4xNDgyOCA4LjUxMzk2IDcuMzc2NjZDOC4yNDg1NiA3Ljk5Njc1IDcuNzMwMTQgOC41NSA3LjAxOTgyIDguNTVDNi41ODE5MiA4LjU0OTk0IDYuMjE3MjIgOC4zMzk3IDUuOTM5NjUgOC4wMzMyQzUuNjYyMTUgOC4zMzk0NyA1LjI5ODAxIDguNTQ5ODkgNC44NjAzNSA4LjU1QzQuNDIyMjkgOC41NSA0LjA1NjkyIDguMzM5ODMgMy43NzkzIDguMDMzMkMzLjUwMTc1IDguMzM5NDUgMy4xMzc3MyA4LjU1IDIuNyA4LjU1QzIuNDUxNDcgOC41NSAyLjI1IDguMzQ4NTMgMi4yNSA4LjFDMi4yNSA3Ljg1MTQ3IDIuNDUxNDcgNy42NSAyLjcgNy42NUMyLjg5MTIgNy42NSAzLjE2NzI2IDcuNDg3OTEgMy4zNjYyMSA3LjAyMzM0TDMuMzk2OTcgNi45NjM1N0MzLjQ3ODA2IDYuODMyMTMgMy42MjI2MSA2Ljc1IDMuNzgwMTggNi43NUMzLjk2MDIgNi43NTAwNyA0LjEyMzMgNi44NTc4MyA0LjE5NDE0IDcuMDIzMzRDNC4zOTMwOSA3LjQ4NzgyIDQuNjY5MTcgNy42NSA0Ljg2MDM1IDcuNjVDNS4wNTE1NiA3LjY0OTggNS4zMjc3MyA3LjQ4NzcyIDUuNTI2NTYgNy4wMjMzNEw1LjU1NzMyIDYuOTYzNTdDNS42MzgzNyA2LjgzMjMyIDUuNzgyMjkgNi43NTAxMiA1LjkzOTY1IDYuNzVDNi4xMTk3NCA2Ljc1IDYuMjgyNzUgNi44NTc3OCA2LjM1MzYxIDcuMDIzMzRDNi41NTI1MSA3LjQ4NzgyIDYuODI4NjIgNy42NDk5IDcuMDE5ODIgNy42NUM3LjIxMTAyIDcuNjUgNy40ODcwOCA3LjQ4Nzg2IDcuNjg2MDMgNy4wMjMzNFpNNS40IDAuOUM0LjQwNTg5IDAuOSAzLjYgMS43MDU4OSAzLjYgMi43VjMuMTVINy4yVjIuN0M3LjIgMS43MDU4OSA2LjM5NDExIDAuOSA1LjQgMC45WiIgZmlsbD0iY3VycmVudENvbG9yIiAvPjwvc3ZnPg==" class="Icon-module-scss-module__lqbdHG__icon" /><span class="body-3">Copy</span>

</div>

</div>

</div>

<div class="Body-module-scss-module__z40yvW__media-column Body-module-scss-module__z40yvW__inline">

<div class="Table-module-scss-module__Z3bHXa__root">

<div class="Table-module-scss-module__Z3bHXa__tableWrapper" aria-label="Summarizing four common failure modes and solutions in long-running AI agents." role="region" tabindex="0">

Agent failure modes and solutions

|  |  |  |
|----|----|----|
| **Problem** | **Initializer Agent Behavior** | **Coding Agent Behavior** |
| Claude declares victory on the entire project too early. | Set up a feature list file: based on the input spec, set up a structured JSON file with a list of end-to-end feature descriptions. | Read the feature list file at the beginning of a session. Choose a single feature to start working on. |
| Claude leaves the environment in a state with bugs or undocumented progress. | An initial git repo and progress notes file is written. | Start the session by reading the progress notes file and git commit logs, and run a basic test on the development server to catch any undocumented bugs. End the session by writing a git commit and progress update. |
| Claude marks features as done prematurely. | Set up a feature list file. | Self-verify all features. Only mark features as “passing” after careful testing. |
| Claude has to spend time figuring out how to run the app. | Write an `init.sh` script that can run the development server. | Start the session by reading `init.sh`. |

</div>

Summarizing four common failure modes and solutions in long-running AI agents.

</div>

</div>

## Future work

This research demonstrates one possible set of solutions in a long-running agent harness to enable the model to make incremental progress across many context windows. However, there remain open questions.

Most notably, it’s still unclear whether a single, general-purpose coding agent performs best across contexts, or if better performance can be achieved through a multi-agent architecture. It seems reasonable that specialized agents like a testing agent, a quality assurance agent, or a code cleanup agent, could do an even better job at sub-tasks across the software development lifecycle.

Additionally, this demo is optimized for full-stack web app development. A future direction is to generalize these findings to other fields. It’s likely that some or all of these lessons can be applied to the types of long-running agentic tasks required in, for example, scientific research or financial modeling.

### Acknowledgements

Written by Justin Young. Special thanks to David Hershey, Prithvi Rajasakeran, Jeremy Hadfield, Naia Bouscal, Michael Tingley, Jesse Mu, Jake Eaton, Marius Buleandara, Maggie Vo, Pedram Navid, Nadine Yasser, and Alex Notov for their contributions.

This work reflects the collective efforts of several teams across Anthropic who made it possible for Claude to safely do long-horizon autonomous software engineering, especially the code RL & Claude Code teams. Interested candidates who would like to contribute are welcome to apply at [anthropic.com/careers](http://anthropic.com/careers).

### Footnotes

1\. We refer to these as separate agents in this context only because they have different initial user prompts. The system prompt, set of tools, and overall agent harness was otherwise identical.

</div>

</div>

<div class="NewsletterSubscribe-module-scss-module__MOPAja__wrapper">

<div class="NewsletterSubscribe-module-scss-module__MOPAja__content">

<div class="NewsletterSubscribe-module-scss-module__MOPAja__text-content">

## Get the developer newsletter

<div class="NewsletterSubscribe-module-scss-module__MOPAja__body">

Product updates, how-tos, community spotlights, and more. Delivered monthly to your inbox.

</div>

</div>

<div class="NewsletterSubscribe-module-scss-module__MOPAja__form-container">

<div class="NewsletterSubscribe-module-scss-module__MOPAja__input-wrapper">

<img src="data:image/svg+xml;base64,PHN2ZyBjbGFzcz0iSWNvbi1tb2R1bGUtc2Nzcy1tb2R1bGVfX2xxYmRIR19faWNvbiIgd2lkdGg9IjIwIiBoZWlnaHQ9IjIwIiB2aWV3Ym94PSIwIDAgMjEgMjEiPjxwYXRoIGQ9Ik00LjE0NTg1IDkuODc0OTJMMTQuNDU4NCA5Ljg3NDkyTDkuNjA0MTkgNS4wNDE1OEwxMC41IDQuMTQ1NzVMMTYuODU0MiAxMC40OTk5TDEwLjUgMTYuODU0MUw5LjYwNDE5IDE1Ljk1ODNMMTQuNDU4NCAxMS4xMjQ5TDQuMTQ1ODUgMTEuMTI0OUw0LjE0NTg1IDkuODc0OTJaIiBmaWxsPSJjdXJyZW50Q29sb3IiIC8+PC9zdmc+" class="Icon-module-scss-module__lqbdHG__icon" />

</div>

Please provide your email address if you'd like to receive our monthly developer newsletter. You can unsubscribe at any time.

</div>

</div>

</div>

</div>

</div>
