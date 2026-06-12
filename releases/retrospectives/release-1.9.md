# Kubeflow 1.9 Release Retrospective

Now that we’ve released 1.9 we would like to follow up with a retrospective to gather feedback on what went well and, most importantly, where we can improve. This document aims to provide a collaboration medium for people to write their feedback on.

The release team will go over the provided feedback, provide a summary and sort the items. Then the team will expose the summary in the next Community Meeting on Tuesday, November 9th.

### Links
- [Handbook](https://github.com/kubeflow/community/blob/master/releases/handbook.md)
- [Release Team](https://github.com/kubeflow/community/blob/master/releases/release-1.9/release-team.md)
- [Timeline](https://github.com/kubeflow/community/blob/master/releases/release-1.9/README.md)

### Rules
- Respectful, solution-oriented communication
- Solutions are found in changing our process and tooling, not in blaming/shaming

## What went well ✅

* [Matteo Mortari] As “Model Registry” a new WG, we really appreciated Ricardo’s and Stefano’s helping us to list the requirements and work needed in order to be in KF 1.9
* [Ricardo] 1.9 was released with +90% of the roadmap done
* [Ricardo] Social Media is working great when sharing release news
* [Julius] We added massive amounts of automatic tests
* [Diego Lovison] CNCF (progress)
* [Josh] good communications, consistent well attended meetings, good meeting notes, kept pretty close to schedule, minimal last minute additions, quality seemed good, few complaints
* [Andrey] Doc's update for this release is AMAZING. Thanks all!

## What could have gone better ⚠️

* [Julius] Release more often with smaller changes, maybe even rolling rolling releases
  * [Julius] Release only when ready and not strictly by timeline
  * [Andrey] Should we stick to releasing the whole Kubeflow stack?
  * [Andrew] Although user can use individual components, Kubeflow distribution is the proof of compatibility between components
* [Julius] More automated testing, that is the most reliable way to do it
* [Diego Lovison] Have a Helm Chart. I know we have the distributions but we announced the release and people weren’t able to just test the release in a simple way.
  * [Julius] Tracked in https://github.com/kubeflow/community-distribution/issues/2730
  * [Andrey] Remove unused components in KF
  * [Ricardo] Maybe use platform components optional?
    * [Julius] This is already possible
  * [Ricardo] Trade-off between maintaining multiple deployment methods
* [Andrew Scribner] Not all core components have very active and responsive working groups
  * [Ricardo] More active contributors
  * [Julius] We already engaged more contributors during the release
  * [Josh] some WG responses could have been improved - Notebooks, Pipelines
* [Andrey V] How to increase the number of distribution participation ?
  * [Ricardo] For some distributions there is only one key contact. We need to find more
* [Ricardo] Some Release Team roles need clarification
* [Ricardo] Lack of coordination between WGs about release cadence
* [Stefano] Survey and user feedback - couldn’t collect much and couldn’t keep up with the initially (too ambitious) proposed plan.
* [Josh] probably can improve announcements, blog was long
* [Helber] Reviews on documentation out of the scope of the PRs
  * Slowed down the merges
  * Duplicated effort creating issues from code reviews
* [Andrey V] Should the release team think about this user feedback: https://github.com/kubeflow/community-distribution/issues/2451 ?

## What we learned

* [Ricardo] Kubeflow release is more complex than I thought
* [Matteo Mortari] maybe difficult to participate weekly, Ricardo did an amazing work in following up with the WG leads, but maybe there could be an improved process to “ping” the WGs or other groups?
* [Stefano] We need a better process to handoff roadmap insights from one release team to the next. When we started with 1.9, we had little knowledge about what should happen next for each working group. We can do a much better job both at keeping track of each WG’s roadmap (upcoming, and future) and also tracking broader user feedback as a release team.
* [Stefano] Keeping technical docs separate from the component codebase makes it much harder to keep them up to date and quickly merge improvements.
* [Josh] Watch schedule for holidays and vacations conflicts, especially near end of release, initial release date should be beginning of month (so if we slip a few weeks, we stay in month)

## Action items

* Figure out the rationale behind using kustomize manifests for deploying Kubeflow. Search for thread in Google Groups
  * [[Public]: Modernize Kustomize (V3) For Kubeflow](https://docs.google.com/document/d/1jBayuR5YvhuGcIVAgB1F_q4NrlzUryZPyI9lCdkFTcw/edit#heading=h.sw48ol3t02xj)
* Promote more reviewers across Working Groups
  * Review: https://github.com/kubeflow/community/pull/737
* Improve Kubeflow documentation to make it easier to find topics like how to contribute
