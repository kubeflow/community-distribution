Kubeflow 1.3 Release Retrospective


# This meeting

- **Zoom**

  - **Part 1 Link: <https://us02web.zoom.us/j/83469905816?pwd=aWM5clpLOTNTMU9udFpkZmV0L01VQT09>**
  - **Part 2 Link:<https://meet.google.com/xub-rfab-tak>**

- **When:**

  - \[done] Tuesday, May 25, 08:00 AM PT
  - \[upcoming] Friday, May 28th, 08:00 AM PT

- **Host:** Yannis Zarkadas &lt;[yanniszark@arrikto.com](mailto:yanniszark@arrikto.com)>

- **Note-Keeping:** Malini Bhandaru &lt;[mbhandaru@vmware.com](mailto:mbhandaru@vmware.com)>

- **Recording:**

  - Part 1: https://www.youtube.com/watch?v=jbVlpsAGaV4
  - Part 2: https://www.youtube.com/watch?v=Pr2vQxUsz_s

- **Based on:** [Kubernetes Retrospective](https://docs.google.com/document/d/1Ay61Wdg_i5ss25kbzpEjT5HLnomlRg7O1acnPujIgC0/edit#heading=h.ukbaidczvy3r)


# How this meeting works

- Please fill in items below, to discuss during the meeting. These items are things you think went well or things that could have gone better.
- Please add your name next to your added item and be ready to elaborate in the meeting.
- Solutions are found in changing our process and tooling, not in blaming/shaming.
- Mute when not speaking.


# Current Processes

- \[yanniszark] Most of the process is documented in issue:<https://github.com/kubeflow/community-distribution/issues/1777>
- \[yanniszark] This old doc from kubeflow/kubeflow is mostly obsolete, but provides some good info on docs:<https://github.com/kubeflow/kubeflow/blob/2d845ee97da9650171701126ad56b34fddd51a7c/docs_dev/releasing.md>


# What went well in 1.3

- \[yanniszark] We successfully released with our new WG community structure.

- \[yanniszark] Major release with a lot of features across Working Groups.

- \[yanniszark] Simplified manifests and installation process.

- \[yanniszark] Sending frequent release updates in the “kubeflow-discuss” mailing list was very useful for people that don’t closely monitor community meetings.

  - \[Malini Bhandaru] I agree the release related emails were on point and highlighted the need of the hour such as distribution completeness/testing etc.
  - \[nakfour] release updates and emails were excellent.

- \[josh] Meeting notes were better documented and sent to the mailing list

- \[rui] Great docs completely new docs on KFP contributed by Google

- \[rui] Openness to refactor very high level things like Getting Started and good collaboration between organizations


# What could have gone better in 1.3


## General

- \[yanniszark] Exact timeline for each release phase was not announced from the start of the release. As a result, some people were confused.

  - **ACTION:Publish exact timeline well in advance**

- \[yanniszark] We had no strict definition of release phases (feature freeze / release candidate, manifests testing, distribution testing), so some people were confused about whether new features could be included.

  - **ACTION:Terminology about release phases. For example, what exactly does “Release Candidate” mean? Define it strictly.**

- \[davidvanderspek and Juana Nakfour ] Automate the way we sync the manifests repo by defining how versions of Kubeflow relate to versions of individual components.

- \[yanniszark] We scheduled some deadlines on days OTHER than community meetings. Deadlines SHOULD always be scheduled on the day of a community meeting OR the one after it, so that we have a chance to sync about the deliverable as a community. -- agree! Malini; mid-week actually good - it protects weekend and Monday holidays

  - \[jamesliu] If we do it on the next day, will people chase the deadline?

- \[yanniszark] We scheduled some deadlines on days that were public holidays. We SHOULD always try to account for holidays before scheduling a deadline.

- \[yanniszark] We did not cut a stable release for kubeflow/kubeflow for 1.3, because there were no additional changes. However, we should always cut a stable release, even if it’s the same as the previous RC.

  - **ACTION:** Add an explicit step, after distributions testing (aka before the final stable release), to cut stable releases for all kubeflow components if needed.

- \[yanniszark] We did not create a GitHub release after cutting a tag. GitHub releases are a GitHub-specific wrapper around git tags. Since these are user-visible objects and we have used them before, we should make sure to continue using them, in order to not confuse users.

  - \[david van der spek] more automation would help here.
  - \[juana] can add a tag now. Yannis has a PR out today to do just that.
  - \[Rui] The latest release in[Kubeflow/Kubeflow](https://github.com/kubeflow/kubeflow) and in [Kubeflow/community-distribution](https://github.com/kubeflow/community-distribution) is still v1.2, this is confusing.
  - \[andrew scribner] People in Statistic Canada were not sure if 1.2 was released. Not clear what the authoritative source was. people keep abreast of change by setting notifications on tags, so such tags help..
  - \[James Liu] Agree to create GitHub release, Google distribution and KFP are currently doing this.**Pinned issues**.<https://docs.google.com/document/d/1KRF4IE48Ueb61DPBKK6fryRWSaNz_urXQOxWf4G_qD8/edit?pli=1#>
  - \[Jeff Fogarty] why did we not make a github release. -
  - \[johnu George]
  - Yannis, not a procedural issue. We should not miss this next time. In this case there were no bugs between release candidate and final, thus it was a forgotten step.
  - **ACTION: Add an explicit step, after the previously-mentioned step to release Kubeflow components.**

- \[yanniszark] In some WGs, there was some confusion over what features should make it in the release. WGs should make an effort to discuss this at the beginning of the release cycle, so that there is no confusion afterwards.

  - \[johnu] Priority tags during releases. In order for people to understand what we are working on.
  - \[Yannis] towards the end of the release these were useful, but several of the items had the same P1 priority which did not help.
  - \[johnu] some items were long standing issues. Eg pipelines - in cluster issues, default installation of kubeflow has -- document known issues, what works/does not/ -- collect these and capture handling them with fixes/workarounds etc. Also crowd source issue triaging, like upvote issues that affect them.
  - \[yannis] perhaps WGs could create an umbrella issue that itemizes issues they plan to work on and prioritize, so everything is in one place.

This also helps with aspirational goals of items they want fixed and what actually gets done -- because some are more convoluted than others.

- \[yanniszark] Some actions required coordination across timezones.

  - **ACTION:** Document that release team members should be added to the release ACL, in order to be able to cut branches themselves: <https://github.com/kubeflow/internal-acls/pull/441>
  - **ACTION:** The release team should have members in different timezones to account to ease the burden.

- \[yanniszark] Many WGs had no established process in place for releasing manifests. Most have adopted a process with release branches, which allow for minor releases without slowing down development in master:<https://github.com/kubeflow/katib/issues/1474>

  - **ACTION:** Make sure that each WG has a clear, documented release process defined for their repos.
  - \[Andrey Velichkevich] could all WGs adopt the same process for manifest release. Branches and tags.
  - \[yannis] a first step would be to document what is currently in place in WG and then compare.

- \[yanniszark] When cutting a new release branch in a repo, Prow testing is not enabled.

  - **ACTION:** Document the exact process. See: <https://github.com/kubeflow/testing/pull/936>

- \[jbottum] we should consider producing a changelog or similar for each release. It would be nice to have a count of issues and PR closed in each release. +1 Malini

  - \[malini] github tag for user related issues, they do it k8s (?)
  - \[yanniszark] changelog per wg?
  - Concept and purpose:[https://github.com/github-changelog-generator/github-changelog-generator
    ](https://github.com/github-changelog-generator/github-changelog-generator)\[Bobgy]: KFP had some painful memories using github-changelog-generator, for context:[\[Release\] Changelog Process after 1.0 · Issue #3920 · kubeflow/pipelines](https://github.com/kubeflow/pipelines/issues/3920)
  - Size features - small/medium/large/extra large. XL might be a feature that gets implemented spread over multiple releases.
  - \[kimonas] We’ve not used changelogs in manifests, but keen on seeing what pipelines is doing to see if we can replicate a common method.
  - Action item: research what tools are available and philosophy - user-facing changes captured in release notes and all changes separately (changelog)

- \[jbottum] we should consider defining terms for distributions to report their release process

  - \[jorge castro] Collect and update for each downstream distribution - GCP, AWS, Azure, OpenShift ..a running tally/status of progress. “Distribution readiness” single page was used in the past. Have distributions to assigning a person, contact person, to contact and get updates when necessary. Create issues and set up notifications for the same.
  - \[yanniszark] Previous issue for tracking distribution progress:<https://github.com/kubeflow/community-distribution/issues/1798>
  - Something that makes this view to be more granular -- like testing has started, expected completion etc.

- \[jbottum] we should request the Working Groups to provide a status to the Release Manager, potentially in writing if they are not going to attend the weekly status call, even if the update is “no change”. Also having a WG just send an update to the kubeflow-discuss list can be a good way for WGs whoo can’t attend a status call to just send an update asynchronously. +1 Malini

- These dependencies per sub-project is a list of dependenciesand their their version. Want consistency on dependency version consistency across all the sub-projects.

  -


- \[jbottum] we should consider a list of dependencies and report on which versions we are expecting to develop and test with i.e. istio, knative, kubernetes,

  - \[yanniszark] SDKs can also have incompatible dependencies
  - \[malini] Perhaps there is a tool for this?

- \[jbottum] At the beginning of each release cycle, each Kubeflow Working Group should schedule and present their current roadmap (what and why)

in a Tuesday Community Meeting.

- \[jorge] perhaps in this meeting also demo the features released in the previous rele +1 Kimonas

- \[James Liu] Currently we are manually testing full fledged Kubeflow, it will be great to identify the scope of supported functionality during Kubeflow release, and write tests to automate this validation. It can reduce the complexity of future releases.

  - \[Andrey V] what platform will we use for testing each release. What is a generic kubernetes? EKS. What do we communicate to our users?
  - \[yannis] we are telling our users we are “pretty confident” and they can select a downstream distribution version to test on their own if they want additional support or could opt for minikube etc..
  - \[malini] how is the base kubernetes selected for each release development effort .. not the bleeding edge.
  - \[yannis] In the past a “popular” one was used but this may need to be formalized, perhaps a matrix of K8 versions that will be explored?

- \[johnu george] - create a release thread/issue and sub-threads for documentation, blocker issues are all taken care of. +1 yannis

- \[Johnu] Like in earlier releases, we can tag issues with release tag and priority so that they can be tracked for each release. This will help in prioritizing features and in bringing better clarity to users. If a fix/feature is agreed upon as p0 for a release, it is a blocker and needs to be fixed before cutting the release. It also becomes easy to figure out what fixes have gone in(Referring to Josh’s earlier comment)

- \[David] version dependencies - KF_serving and pipelines version were different in notebook -- such as SDK etc. These should be made compatible.

- \[Malini] libraries of third party dependencies too - example boto3.

- \[yannis] PR in test repo too.

- \[nakfour] The time between KF 1.3 first cut and distribution support was too short, I think 1-2wks

- \[yannis] we could send more frequent updates when there are delays

- \[andrey v] - WGs are using different release processes with respect to cutting the branch and tagging.

- \[yannis] kfserving, katib and notebook use release branches. Pipelines uses tags. Release branches bring the benefit of allowing continued work on the master.

- \[andrey] istio follows new branch from master when they are ready to do a release.

- \[yannis] istio then cheery picks any bug fixes and merges to the release branch. Katib has documented this process. Similar documentation of this available in kubeflow/kubeflow.

- \[andrey v] what about a consistent way to push images to repositories/registries, to publish images. Registry provider.. Andrey to provide additional details here.

  - ECR issue:<https://github.com/kubeflow/kubeflow/issues/5922>

- \[johnu] allow sub-projects to use their own registries

  - <https://github.com/kubeflow/kubeflow/blob/master/releasing/README.md>

- \[nakfour] release delays need more elaborate information on blocking issues and estimated new release dates

- \[Andrey] Can we follow the same release process for all WGs? Image registries, CI/CD, etc.

  - Clear plan for all WGs to follow a single release process? Do we want a single release process?


## Docs

- \[yanniszark] In our current process, we first release and then focus on docs. Should we instead focus on docs when a feature goes in and not release until we have good documentation? \[+1 Rui]

- \[yanniszark] Is the[current process](https://github.com/kubeflow/kubeflow/blob/2d845ee97da9650171701126ad56b34fddd51a7c/docs_dev/releasing.md#version-the-website) for the website up-to-date? Who has the permissions to follow it?

  - \[rui] Not 100% up to date, but still very relevant

- \[rui] WG ownership of their docs was low. We had things like training operators outdated for months

- \[malini] would it make sense to have advertised doc hackathon days? To get all eyes on it.

- \[shannon Bradshaw] pro-actively call out updates that will break some doc obsolete - impact of features on doc

- \[david] code-doc if they co-reside, more likely they will be in sync as opposed to a separate website.
  -\[Bobgy] +100 to this, ideally PRs should contain both doc and code changes at the same time.[Breaking up the website to each WG is a prerequisite.](https://github.com/kubeflow/website/issues/2293#issuecomment-718481321)

- \[yannis] would like to suggest that WG consider doc writing as part of feature release as opposed to a separate after step. Completeness is implementation with its docs. - Shannon, Malini etc agree on this.

- \[josh] how much does the open source documentation have to do given there may be different plugins/implementations. Should we articulate some template/minimum expectations wrt docs.

- \[david] what parts of the docs fall in the purview of KF and what falls into the distros.

- \[yannis] identify an issue that is extreme to clarify the above as example.

- \[josh] Users should provide feedback about whether some docs are adequate. Users should be part of the release process to look at the docs on par with developers. Users to QA/vet the docs - perhaps when the RC goes out. A comment period.

- \[yannis] distros are our first users. But end users who consume it all.

- \[josh] we get dinged on docs, let us formally invite them to be part of the process for testing it. There are 2 sets of users, beta and GA users, giving feedback during document creation.

- \[malini]the docs do have links within to help people file issues.

- \[yannis] demonstrated what is available

- \[josh]**docs sprints** -- users/everyone take a look and provide comments. A lot of this has fallen on Rui and do not want to overload him, people to help.

- \[kimonas] feature complete requires documentation. A template too for new feature proposal, what all it affects -- APIs/tests, documentation, performance.

- \[andrey] all working groups should follow the same pattern. +1 Kimonas

- \[yannis] PR template

- \[yannis] release handbook


# Next Steps

- For 1.4, one of the core deliverables will be to contribute upstream a detailed release document from all the learning so far, so after 1.4, everyone can follow it and the release process can really scale.
- The KFP and KFServing SDKs had conflicting dependencies making them incompatible with each other. All SDKs should have the same dependency requirements so they are compatible with each other.
