# Kubeflow AI Reference Platform Release Handbook

## Goals

- Use Calendar Versioning (CalVer) to clearly indicate when releases occur.
- Provide a predictable release schedule with clear dates and phases for distributions, working groups, and the community.
- Minimize release overhead through automation and asynchronous communication.
- Enable fast iteration through patch releases.

## Release Meetings and Communication
- Create a new Release Management team on Slack for asynchronous communication within the team.
- Meetings are bi-weekly during development and weekly during RC testing as needed.

## Versioning (CalVer)

Kubeflow uses [Calendar Versioning](https://calver.org/) with format `YY.MM[.PATCH]`. Two base releases are targeted per year.

All releases are cut from `kubeflow/community-distribution`.

### Release Types

| Type | Format | Rules | Examples |
|------|--------|-------|----------|
| Release Candidate | `YY.MM-rc.N` | `rc.1` mandatory; additional RCs optional | Tag: `26.03-rc.1`, `26.03-rc.2` |
| Base Release | `YY.MM` | Initial release for a version | Tag: `26.03`; Branch: `release-26.03` |
| Patch Release | `YY.MM.PATCH` | Bug-fix; try to avoid breaking changes; sequential numbering | Tag: `26.03.1`, `26.03.2` |


## Timeline
- Week 0 - (Roadmap) Release team and WG Leads discuss the roadmap.
- Weeks 2, 4, 6, 8 - (Development) Synchronize on challenges, changes, and blockers.
- Week 9 - (Feature Freeze) Finalize features, prepare documentation. Cut `rc.1`.
- Weeks 10-12 - (RC1 Testing) Community and distribution testing.
- Week 13 - (Release Decision) Promote `rc.1` to final, or cut `rc.2` if blockers reported.
- Weeks 14-15 - (RC2 Testing, if needed) Testing period for `rc.2`.
- Week 16 - (Final Release, if RC2 was needed) Promote `rc.2` to final.

## People and Roles

### Release Management Team
The Release Management Team is composed of: Release Manager, WG leads / liaisons, and Product Manager.
Release team liaisons will be responsible not only for the communication but for contributing to the release with documentation, source code, PRs review, etc, according to their skills and motivation.

### Release Manager
- Own the overall Kubeflow release process and make go/no-go decisions
- Promote best practices for release and software development
- Coordinate with WG leads/liaisons on dates, deliverables, and blockers
- Communicate release status via Slack, mailing list, and community meetings
- Ensure branches and tags are cut for each release phase
- Host release team meetings
- Review and approve the release blog and slides

### Release Manager Shadows
Release Manager Shadows are community members interested in becoming a Release Manager. They work closely with the current Release Manager throughout the release cycle to learn the process and are prepared to lead future releases.

### Product Manager
- Ensure documentation is updated and accurate for the release
- Identify and track issues that require documentation updates
- Coordinate and publish the release blog post
- Prepare the final release presentation and slides

## Preparation

- [ ] [Assemble a release team](https://github.com/kubeflow/community/issues/571)
- [ ] Create a new [release project](https://github.com/orgs/kubeflow/projects) to track issues and pull requests related to the release
- [ ] Working groups broadly think about features **with priorities** they want to land for that cycle, have internal discussions, perhaps groom a backlog from previous cycle, get issues triaged, etc.
- [ ] Update the release manager and members of the Release Team in the [kubeflow/internal-acls](https://github.com/kubeflow/internal-acls/pull/545)
- [ ] Update the [owners file](https://github.com/kubeflow/community/blob/master/releases/OWNERS) by appointing the new release manager as approver and the rest of the release team as reviewers. Add the previous release manager to the list of emeritus approvers.
- [ ] Establish a regular release team meeting as appropriate on the schedule and update the [Kubeflow release team calendar](https://zoom-lfx.platform.linuxfoundation.org/meeting/92113176338?password=883a2c39-41a9-4395-b9f2-d2bd73e8c39e)
- [ ] [Propose a release timeline](https://github.com/kubeflow/community/pull/558), announce the schedule to [kubeflow-discuss mailing list](https://groups.google.com/g/kubeflow-discuss), and get lazy consensus on the release schedule from the WG leads
  - Review the criteria for the timeline below
- [ ] Ensure schedule also accounts for the patch releases after the base release
- [ ] Create one [release tracking issue](https://github.com/kubeflow/community-distribution/issues/2194) for all WGs, distributions representatives, and the community to track
- [ ] Start a discussion on [Kubeflow dependency versions](https://github.com/kubeflow/community-distribution/issues/2207) to support for the release

Criteria for timeline that the team needs to consider
- Holidays around the world that coincide with members of the release team, WG representatives, and distro representatives.
- Enterprise budgeting/approval lifecycle. (aka users have their own usage and purchase requirements and deadlines)
- Kubecon dates - let us not hard block on events, but keep them in mind since we know community members might get doublebooked.
- Associated events (aka. AI Day at Kubecon, Tensorflow events) - we want to keep them in mind.

**Success Criteria:** Release team selected, release schedule sent to kubeflow-discuss, all release team members have the proper permissions and are meeting regularly.

### Implementation
**Actions for the Release Team:**
- We aim to always include the latest release from each working group unless specified otherwise.
- Make pull requests to update the manifests for the different WGs
- Identify, early in the first week, bugs at risk. These should either be aggressively fixed or punted
- Request a list of features and deprecations, from the Working Groups, that require updates to the documentation
- Ensure the provided component versions match the documentation
- Work alongside the Working Groups to bring the documentation up to date
- Create a [new version dropdown and update the website version](https://github.com/kubeflow/website/pull/3333)
- Add new [release page with component and dependency versions](https://github.com/kubeflow/website/pull/3332)
- Work with the WGs to build the release notes and slides
- Start creating the draft for the official blog post and collating information from the Working Groups
    - (Optional but encouraged) Working Groups start drafting WG-specific blog
        posts, deep diving into their respective areas
- Preparation for social media posts can start at the beginning of this phase
- Release Manager: List the features, and ideally with documentation, that made it into the release
- Publish release blog post
- (Optional but encouraged) Working Groups publish individual deep dive blog posts on features or other work they’d like to see highlighted.
- Publish social media posts
- Send [release announcement](https://groups.google.com/g/kubeflow-discuss/c/qDRvrLPHU70/m/ORKN14DzCQAJ) to kubeflow-discuss

**Success Criteria:**
- Documentation for this release completed with minimum following pages updated and a [new version
in the website is cut](https://github.com/kubeflow/kubeflow/blob/master/docs_dev/releasing.md#version-the-website).
- [Installing Kubeflow](https://www.kubeflow.org/docs/started/installing-kubeflow/)
- [Release Page](https://www.kubeflow.org/docs/releases/)
- [Distributions](https://www.kubeflow.org/docs/distributions/) and related pages underneath

## Post Release

### Patch Release
Planning for first patch release begins. The importance of bugs is left to the judgement of the Working Group leads and the Release Manager to decide.

### Release Retrospective

The Release Team should host a [blameless](https://sre.google/sre-book/postmortem-culture/)
retrospective and capture notes with the community. The aim of this document
is for everyone to chime in and discuss what went well and what could be improved.

### Prepare for the Next Release
- Release Manager nominates the next release manager and discusses with the release team
- Send out a [call for participation](https://groups.google.com/g/kubeflow-discuss/c/mdpnTxYv7kM/m/dO9ny3woCQAJ) for the next release
- (if needed) Update the release handbook
- Work to close any remaining tasks
- Close all release tracking issues
- Give Kubeflow release calendar access to the new release manager
