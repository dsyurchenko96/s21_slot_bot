# TODO: move to graphql files?

Q_GET_USER = """
query getCurrentUser {
  user {
    getCurrentUser {
      ...CurrentUser
      __typename
    }
    __typename
  }
}

fragment CurrentUser on User {
  id
  avatarUrl
  login
  firstName
  middleName
  lastName
  currentSchoolStudentId
  __typename
}
""".strip()

Q_GET_CUR_PROJECTS = """
query getStudentCurrentProjects($userId: ID!) {
  student {
    getStudentCurrentProjects(userId: $userId) {
      ...StudentProjectItem
      __typename
    }
    __typename
  }
}

fragment StudentProjectItem on StudentItem {
  goalId
  name
  description
  experience
  dateTime
  finalPercentage
  laboriousness
  executionType
  goalStatus
  courseType
  displayedCourseStatus
  amountAnswers
  amountMembers
  amountJoinedMembers
  amountReviewedAnswers
  amountCodeReviewMembers
  amountCurrentCodeReviewMembers
  groupName
  localCourseId
  __typename
}
""".strip()

Q_GET_LOCAL_COURSE_GOALS = """
query getLocalCourseGoals($localCourseId: ID!) {
  course {
    getLocalCourseGoals(localCourseId: $localCourseId) {
      localCourseId
      globalCourseId
      courseName
      courseType
      localCourseGoals {
        ...LocalCourse
        __typename
      }
      __typename
    }
    __typename
  }
}
fragment LocalCourse on LocalCourseGoalInformation {
  localCourseGoalId
  goalId
  goalName
  description
  projectHours
  signUpDate
  beginDate
  deadlineDate
  checkDate
  isContentAvailable
  executionType
  finalPoint
  finalPercentage
  status
  periodSettings
  retriesUsed
  statusUpdateDate
  retrySettings {
    ...RetrySettings
    __typename
  }
  __typename
}
fragment RetrySettings on ModuleAttemptsSettings {
  maxModuleAttempts
  isUnlimitedAttempts
  __typename
}
""".strip()

Q_GET_PROJECT_INFO = """
query getProjectInfo($goalId: ID!, $studentId: UUID!) {
  school21 {
    getModuleById(goalId: $goalId, studentId: $studentId) {
      ...ProjectInfo
      __typename
    }
    getModuleCoverInformation(goalId: $goalId, studentId: $studentId) {
      ...ModuleCoverInfo
      __typename
    }
    getP2PChecksInfo(goalId: $goalId, studentId: $studentId) {
      ...P2PInfo
      __typename
    }
    getStudentCodeReviewByGoalId(goalId: $goalId, studentId: $studentId) {
      ...StudentsCodeReview
      __typename
    }
    __typename
  }
}

fragment ProjectInfo on StudentModule {
  id
  moduleTitle
  finalPercentage
  finalPoint
  goalExecutionType
  displayedGoalStatus
  accessBeforeStartProgress
  resultModuleCompletion
  finishedExecutionDateByScheduler
  durationFromStageSubjectGroupPlan
  currentAttemptNumber
  isDeadlineFree
  isRetryAvailable
  localCourseId
  courseBaseParameters {
    isGradedCourse
    __typename
  }
  teamSettings {
    ...teamSettingsInfo
    __typename
  }
  studyModule {
    id
    idea
    duration
    goalPoint
    retrySettings {
      ...RetrySettings
      __typename
    }
    levels {
      id
      goalElements {
        id
        tasks {
          id
          taskId
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
  currentTask {
    ...CurrentInternshipTaskInfo
    __typename
  }
  __typename
}

fragment teamSettingsInfo on TeamSettings {
  teamCreateOption
  minAmountMember
  maxAmountMember
  enableSurrenderTeam
  __typename
}

fragment RetrySettings on ModuleAttemptsSettings {
  maxModuleAttempts
  isUnlimitedAttempts
  __typename
}

fragment CurrentInternshipTaskInfo on StudentTask {
  id
  taskId
  task {
    id
    assignmentType
    taskSolutionType
    studentTaskAdditionalAttributes {
      cookiesCount
      maxCodeReviewCount
      codeReviewCost
      ciCdMode
      __typename
    }
    checkTypes
    taskSolutionType
    __typename
  }
  lastAnswer {
    id
    __typename
  }
  teamSettings {
    ...teamSettingsInfo
    __typename
  }
  __typename
}

fragment ModuleCoverInfo on ModuleCoverInformation {
  isOwnStudentTimeline
  softSkills {
    softSkillId
    softSkillName
    totalPower
    maxPower
    currentUserPower
    achievedUserPower
    teamRole
    __typename
  }
  timeline {
    ...TimelineItem
    __typename
  }
  __typename
}

fragment TimelineItem on ProjectTimelineItem {
  type
  status
  start
  end
  children {
    ...TimelineItemChildren
    __typename
  }
  __typename
}

fragment TimelineItemChildren on ProjectTimelineItem {
  type
  elementType
  status
  start
  end
  order
  __typename
}

fragment P2PInfo on P2PChecksInfo {
  cookiesCount
  periodOfVerification
  projectReviewsInfo {
    ...ProjectReviewsInfo
    __typename
  }
  __typename
}

fragment ProjectReviewsInfo on ProjectReviewsInfo {
  reviewByStudentCount
  relevantReviewByStudentsCount
  reviewByInspectionStaffCount
  relevantReviewByInspectionStaffCount
  p2pRequirementStatus
  __typename
}

fragment StudentsCodeReview on StudentCodeReviewsWithCountRound {
  countRound1
  countRound2
  codeReviewsInfo {
    maxCodeReviewCount
    codeReviewDuration
    codeReviewCost
    __typename
  }
  __typename
}
""".strip()

Q_GET_MODULE = """
query calendarGetModule($moduleId: ID!) {
  student {
    getModuleById(goalId: $moduleId) {
      id
      moduleTitle
      subjectTitle
      goalExecutionType
      currentTask {
        ...CalendarStudentTask
        __typename
      }
      __typename
    }
    __typename
  }
}

fragment CalendarStudentTask on StudentTask {
  id
  taskId
  task {
    id
    studentTaskAdditionalAttributes {
      ...CalendarStudentTaskAdditionalAttributes
      __typename
    }
    assignmentType
    __typename
  }
  lastAnswer {
    id
    __typename
  }
  __typename
}

fragment CalendarStudentTaskAdditionalAttributes on StudentTaskAdditionalAttributes {
  cookiesCount
  __typename
}
""".strip()

Q_GET_SLOTS = """
query calendarGetNameLessStudentTimeslotsForReview($from: DateTime!, $taskId: ID!, $to: DateTime!) {
  student {
    getNameLessStudentTimeslotsForReview(from: $from, taskId: $taskId, to: $to) {
      checkDuration
      projectReviewsInfo {
        ...ProjectReviewsInfo
        __typename
      }
      timeSlots {
        ...CalendarNameLessTimeslot
        __typename
      }
      __typename
    }
    __typename
  }
}

fragment ProjectReviewsInfo on ProjectReviewsInfo {
  reviewByStudentCount
  relevantReviewByStudentsCount
  reviewByInspectionStaffCount
  relevantReviewByInspectionStaffCount
  p2pRequirementStatus
  __typename
}

fragment CalendarNameLessTimeslot on CalendarNamelessTimeSlot {
  start
  end
  validStartTimes
  staffSlot
  __typename
}
""".strip()

Q_GET_BOOKINGS = """
query calendarGetMyBookings($from: DateTime!, $to: DateTime!) {
  student {
    getMyCalendarBookings(from: $from, to: $to) {
      ...CalendarReviewBooking
      __typename
    }
    __typename
  }
}

fragment CalendarReviewBooking on CalendarBooking {
  id
  answerId
  eventSlotId
  task {
    id
    goalId
    goalName
    studentTaskAdditionalAttributes {
      cookiesCount
      __typename
    }
    assignmentType
    __typename
  }
  eventSlot {
    id
    start
    end
    event {
      eventUserRole
      eventCode
      __typename
    }
    school {
      shortName
      __typename
    }
    __typename
  }
  verifierUser {
    ...CalendarReviewUser
    __typename
  }
  verifiableInfo {
    verifiableStudents {
      ...VerifiableStudentItem
      __typename
    }
    team {
      name
      __typename
    }
    __typename
  }
  bookingStatus
  isOnline
  vcLinkUrl
  additionalChecklist {
    filledChecklistId
    filledChecklistStatusRecordingEnum
    __typename
  }
  __typename
}

fragment CalendarReviewUser on User {
  id
  login
  __typename
}

fragment VerifiableStudentItem on VerifiableStudent {
  userId
  login
  avatarUrl
  levelCode
  isTeamLead
  cookiesCount
  codeReviewPoints
  school {
    shortName
    __typename
  }
  __typename
}
"""

Q_BOOK = """
mutation calendarAddBookingToEventSlot($answerId: ID!, $startTime: DateTime!, $wasStaffSlotChosen: Boolean!, $isOnline: Boolean) {
  student {
    addBookingP2PToEventSlot(
      answerId: $answerId
      startTime: $startTime
      wasStaffSlotChosen: $wasStaffSlotChosen
      isOnline: $isOnline
    ) {
      id
      __typename
    }
    __typename
  }
}

""".strip()
