# Test Scenarios for Healthcare Support Agent

## Part 1: Routine Assistance

### Scenario 1: User Authentication
**Agent:**  
"Hello, you’ve reached the Healthcare Support Service. For your security, I first need to verify your identity. Could you please provide your full name, date of birth, and phone number?"

**User:**  
"My name is Alice Brown, I was born on 1987-04-12, and my phone number is 5551234567."

- *Action:* The agent triggers the `authenticate_user` function.  
- *Result:* Authentication is successful.

**Agent:**  
"Thank you, Alice. How can I assist you today? Please tell me your request in brief."

---

### Scenario 2: Appointment Scheduling
**User:**  
"I’d like to schedule a follow-up consultation for next Tuesday at 10:30 AM."

- *Action:* The agent classifies this as an Appointment Scheduling request, gathers additional information, and triggers the `schedule_appointment` function.  
- *Result:* Appointment is successfully scheduled.

**Agent:**  
"Your follow-up consultation for next Tuesday at 10:30 AM has been scheduled. Is there anything else you’d like to address today?"

---

### Scenario 3: Prescription Refill
**User:**  
"Yes, I need a refill on my prescription for Metformin."

- *Action:* The agent recognizes this as a Prescription Refill request and triggers the `refill_prescription` function.  
- *Result:* Prescription refill request is successfully submitted.

**Agent:**  
"I have successfully submitted your prescription refill request for Metformin. The pharmacy on record will process it shortly. Would you like any additional information?"

---

### Scenario 4: Medication Information
**User:**  
"Could you tell me more about Metformin—its uses and common side effects?"

- *Action:* The agent identifies this as a Medication Information request and triggers the `lookup_medication_info` function.  
- *Result:* Medication information is retrieved.

**Agent:**  
"Metformin is commonly used for the treatment of type 2 diabetes. It helps lower blood sugar levels, and common side effects include nausea and diarrhea. Do you need help with anything else?"

---

### Scenario 5: Insurance Authorization Assistance
**User:**  
"Actually, I also need assistance with my insurance authorization for a new medication plan involving Lisinopril."

- *Action:* The agent classifies this as an Insurance or Authorization Assistance request and triggers the `evaluate_prior_authorization` function.  
- *Result:* Initial evaluation for prior authorization is complete.

**Agent:**  
"Your request for prior authorization for Lisinopril has been reviewed. Further clinical validation may be required, but the initial evaluation is complete. Is there anything else I can help you with in this session?"

---

## Part 2: Emergency Escalation

### Scenario 6: Critical Health Concern
**User:**  
"Wait—I'm now experiencing severe chest pain!"

- *Action:* The agent immediately recognizes an Emergency or Urgent Health Concern and bypasses the usual authentication flow.  
- *Response:* The agent triggers the `escalate_emergency` function.

**Agent:**  
"Understood. Please hold while I connect you to emergency services immediately."

- *Result:* Emergency escalation is completed, and a human healthcare agent is connected.

**Agent:**  
"An emergency has been escalated. A human healthcare agent is now being connected to you. Please remain on the line for immediate assistance."
