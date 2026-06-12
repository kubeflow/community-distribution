# Kubeflow 1.4 Release Retrospective
- [Original Documentation](https://docs.google.com/document/d/119PCr2h3Wwm7XA_qHqtda017Q--yWPF9u7nuUWo0ZnY/edit?usp=sharing)

Now that we’ve released 1.4 we would like to follow up with a retrospective to gather feedback on what went well and, most importantly, where we can improve. This document aims to provide a collaboration medium for people to write their feedback on.

The release team will go over the provided feedback on Monday, November 8th, provide a summary and sort the items. Then the team will expose the summary in the next Community Meeting on Tuesday, November 9th.

### Links
- [Handbook](https://github.com/kubeflow/community-distribution/blob/v1.4.0/docs/releases/handbook.md)
- [Release Team](https://github.com/kubeflow/community-distribution/blob/v1.4.0/docs/releases/release-1.4/release-team.md)
- [Timeline](https://github.com/kubeflow/community-distribution/tree/v1.4.0/docs/releases/release-1.4)
- Recordings
  - [Part 1](https://drive.google.com/file/d/1MxOzR4wgvETfhLv_74wEkAdkElGSPeTm/view)
  - [Part 2](https://drive.google.com/file/d/1wz-jIAOSw3N7V9XHxPoDIEfv5hOdFFn1/view)

### Rules
- Respectful, solution-oriented communication
- Solutions are found in changing our process and tooling, not in blaming/shaming

# Part 1

## What went well ✅
- [Kimonas Sotirchos] The timeline was defined from the start of the release process
- [Kimonas Sotirchos] More clear overview of the different phases
- [Kimonas Sotirchos] Very good and timely communication with all WG leads
- [Kimonas Sotirchos] A dedicated release team
- [Kimonas Sotirchos] Regular meetings to discuss the progress of the release
  - **[Action Item]** Any announcement the release team send out, include links to release resources - add to release handbook
  - **[Action Item]** Add release info to the website for visibility - create an issue to track
- [Josh Bottum] Better communication with the distribution owners
- [Josh Bottum] Better quality of the release
  - [Kimonas Sotirchos] Release timeline went well with WG timelines
  - **[Action Item]** Get release schedule feedback from WG - add to release handbook
- [Josh Bottum] Feature roadmap presentation for the community in the beginning of the release
  - [Anna] It could help the WGs to start having the release in mind and start planning
  - [Andrey] Some WG might not have a new release synced with the KF release. Let’s not enforce that WGs also sync their releases with KF
  - [Kimonas] Lets actually discuss this more after we do a first feedback meet with WGs

## What could have gone better ⚠️
- [Kimonas Sotirchos] More emails to the mailing list, so that people not following GitHub can also stay up to date with what’s going on, blockers etc
  - [Anna] Is there a better way to get WG and/or distribution owners attention
  - [Andrey] We also have the announcements channel
  - [Anna] We could also create slack groups
  - [Kimonas] Lets try to keep the context in GitHub though, even if we use slack
  - **[Action Item]** Duplicate kubeflow-discuss announcements in slack - add to release handbook
- [Kimonas Sotirchos] An automated way of syncing manifests from other repos to the manifests repo
- [Kimonas Sotirchos] We had a manual process for testing the provided manifests, which required cycles
  - [Kimonas] The AutoML WG leads had created a notebook that the GCP folks used for evaluating their distro. We could convert to a py script and run it with prow [https://github.com/kubeflow/pipelines/blob/master/samples/contrib/kubeflow-e2e-mnist/kubeflow-e2e-mnist.ipynb](https://github.com/kubeflow/pipelines/blob/master/samples/contrib/kubeflow-e2e-mnist/kubeflow-e2e-mnist.ipynb)
  - [Juana] Maybe we could only run this nightly
  - [Andrew Scribner] Conformance tests were raised in the kubeflow conformance program discussion.  It would be ideal if these tests were sync’d as the goal of the tests sound very similar - we are trying to prove we have a fully functioning kubeflow **(Discussed in Part 2)**
    - [Anna] Shouldn’t the provided manifests after each release also pass the conformance tests? +1 Kimonas
    - [Kimonas] We could make this more explicit as we go forward
- [Andrew Scribner] Create an issue to track [the release] +1 Kimonas **(Discussed in Part 2)**
  - **[Action Item]** Add the step to create an issue in the handbook
- [Kimonas Sotirchos] We should have cut the branch for 1.3 previous release early on. The 1.3 docs ended up having some content that corresponded to 1.4
  - **[Action Item]** Update docs for versioning/cutting branch for the release to follow the new process
- [Kimonas Sotirchos] A lot of docs PRs still happened in the end of the release timeline
  - [Shannon] Provide guideline on how doc process/reviews work
  - [Andrey] Define owners for each website file
  - [Anna] We could have prow to check if a PR has a corresponding docs PR
  - **[Action Item]** Remove documentation phase and enforce WG to have docs as part of development phase - propose to WG leads

# Part 2
- [Josh Bottum] Document the process for the release blog post
- [Josh Bottum] Document the process for the release video presentation
- [Josh Bottum] We could use more user input on features and more user contributions
  - [Issue](https://github.com/kubeflow/community/issues/530) already created to track
- [Andrey Velichkevich] Decrease the Feature Freeze timeline
  - [kimonas] We can move the Manifests Testing to the second week in the Feature Freeze phase
  - [kimonas] Lets also write down the main criteria for reducing feature freeze:
    - Having enough CI/CD in place to run tests in an automated manner
    - Ask if the WG leads feel comfortable stabilizing their components with the proposed time frame (for example 1 week of Feature Freeze in the future)
    - [Andrey] It would be good to have the big PRs merged even before the feature freeze, since we will also be tackling the docs PRs for these features in parallel +1 Kimonas
    - [Anna] It’s also good to explicitly mention the deadlines
- [Anna Jung] Team selection process
  - [Anna] Should we keep on having nominations? +1 Kimonas
  - [Anna] Shouldn’t the release team be able to select the next release team? +1 Kimonas
  - [Anna] We should still use the mailing list to ask for volunteers for shadows, but not for the lead roles +1 Kimonas
  - [Anna] Let’s also have a limit to how many times someone can run the release consecutively. This will help ensure that people can come, use the handbook and successfully drive the release +1 Kimonas
  - [Anna] We should start defining even more the skill and effort required for the role of the Release Manager, so that people can be prepared for what they are signing in for
- [Anna Jung] Delay in release
- [Anna Jung] Responsibility of the release team
  - [Anna] Let’s also ensure we ask new members if they would like to lead following releases
  - [Kimonas] Let’s think about removing one of the Release Team member or Shadow roles
- [Anna Jung] Add release candidates to the timeline
  - Lets add this information in the tables in the [timeline](https://github.com/kubeflow/community-distribution/tree/master/docs/releases/release-1.4#timeline) and [handbook](https://github.com/kubeflow/community-distribution/blob/master/docs/releases/handbook.md#timeline)
- Move release docs to community rep? [Anna Jung]
  - **[Action Item]** Create an issue to move the kubeflow/community-distribution/docs/releases folder under kubeflow/community
  - [Kimonas] Let’s ensure that the OWNERS file will include the release team to allow us to keep on iterating fast
