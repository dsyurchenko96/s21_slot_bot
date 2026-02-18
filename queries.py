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
