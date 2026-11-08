# llm-bench

A benchmark that gives coding tasks to LLMs behind OpenAI-compatible servers and scores the code they return by building and testing it.

## Tasks

**Task**:
One coding problem in one language, made of a prompt, a harness and a reference solution.
_Avoid_: Problem, challenge, test case

**Write task**:
A task that asks the model to write code from a specification.
_Avoid_: "Write this" task, implementation task

**Fix task**:
A task that gives the model broken code and asks for a corrected version.
_Avoid_: "Fix this code" task, debug task, repair task

**Prompt**:
The task's statement, sent to the model word for word. It is separate from the system prompt, which is shared by all tasks.
_Avoid_: Instructions, problem statement

**Harness**:
The hidden test program that decides whether a solution passes a task.
_Avoid_: Test suite, tests, checker

**Reference solution**:
A known-correct solution kept with the task to prove the harness can be passed. It is never shown to models.
_Avoid_: Golden solution, expected solution

## Models and servers

**Endpoint**:
A named OpenAI-compatible server address being benchmarked. Each endpoint has its own results.
_Avoid_: Backend, server (the server is the software behind an endpoint)

**Model**:
One model ID listed by an endpoint.

**Warm-up**:
A one-token request that loads a model before its first task, so load time is not charged to that task.
_Avoid_: Probe, load request

**Context check**:
A test, run once per model, of whether the endpoint keeps a full-size prompt without truncating or refusing it.

## Runs and trials

**Run**:
One run of the benchmark against one or more endpoints, from start to finish or interruption.
_Avoid_: Session, invocation

**Trial**:
One model working on one task, through all its attempts, with one recorded result. A model can have several trials of the same task, numbered in order.
_Avoid_: Run, repeat, sample

**Round**:
One trial of every task in the task set for one model. A model's score is measured per round. Trials of different tasks are counted separately, so a round doesn't have to be complete.
_Avoid_: Run, pass, sweep

## Attempts

**Attempt**:
One reply from the model, plus the build and test of the solution taken from it.
_Avoid_: Try, turn

**Retry**:
Any attempt after the first. It includes feedback from the previous failure.

**Feedback**:
The build or test output of a failed attempt, sent to the model with the next attempt.
_Avoid_: Error message, hint

**Reply**:
The text the model returns for one request.
_Avoid_: Response, answer, completion

**Solution**:
The code taken from a reply and tested against the harness.
_Avoid_: Answer, submission

**Fail stage**:
Where the last attempt failed: build, test, time limit, no code, request, load or budget.

**Request error**:
A failure caused by the server, not by the model's reply: an HTTP error, a malformed reply or a dropped connection.
_Avoid_: Request-level failure, model error

**Length finish**:
A reply cut off because it reached the completion token limit.
_Avoid_: Truncation

## Comparability

**Settings**:
Everything besides the tasks themselves that can change a trial's result, such as the benchmark version, system prompt, limits and request parameters.
_Avoid_: Options, configuration

**Task version**:
A task's exact content: its prompt, harness and the way it is built and tested. Changing any of these creates a new version of the task.
_Avoid_: Config, task revision

**Comparable**:
Trials are comparable when they share the same settings and task version. Two models' scores are comparable only when they come from comparable trials of the same tasks.

## Scores

**Pass@1**:
The number of tasks in a round that a model passes on the first attempt.

**Passed**:
The number of tasks in a round that a model passes within the allowed number of attempts.

**Reasoning tokens**:
The part of a reply's completion tokens a thinking model spends on reasoning before its answer, as reported by the server. Not every server reports them.

**Throughput**:
Completion tokens per second of reply time (`tok/s`), over the trials that ended with a reply and reported token usage. It includes prompt processing and queueing, so it's lower than the pure generation speed.
_Avoid_: Speed (ambiguous with generation speed)
