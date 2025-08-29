# Enhanced Multi-Turn Load Testing Framework

## Overview

This enhanced load testing framework provides comprehensive load testing capabilities with detailed per-turn statistics and configurable conversation turn depth, enabling realistic multi-turn conversation simulation for your real-time voice AI agent.

## Key Features

### Detailed Per-Turn Statistics
- Comprehensive metrics: P50, P75, P90, P95, P99, P99.9 percentiles for every metric
- Per-turn breakdown: Individual timing analysis for each conversation turn
- Turn position analysis: How performance varies by turn number (1st turn vs 5th turn)
- Template comparison: Performance differences between conversation scenarios

### Concurrency Analysis
- Peak concurrent conversation tracking
- Average concurrency over test duration
- Timeline analysis of concurrent connections
- Latency impact under different concurrency levels

### Conversation Recording
- Random sampling of conversations for detailed analysis
- Configurable recording percentage (default: 20% of conversations)
- Full conversation flow capture including latencies and errors
- Exported conversation records for manual review

### Simplified 2-Scenario Focus
- `insurance_inquiry`: 5-turn detailed insurance conversation
- `quick_question`: 3-turn simple account inquiry
- Focused analysis: Deep insights without scenario complexity
- **Speech Recognition Latency**: Time from audio end to first agent response
- **Agent Processing Latency**: Time from first to last agent response  
- **End-to-End Latency**: Total turn completion time
- **Audio Send Duration**: Time to transmit user audio
- **Turn Success Rate**: Percentage of successful turns per position

## 🛠️ Setup Instructions

### 1. Generate Audio Files for 2 Scenarios

```bash
# Generate audio for simplified 2-scenario system
python tests/load/audio_generator.py \
  --max-turns 5 \
  --scenarios insurance_inquiry quick_question

# Clear cache and regenerate if needed
python tests/load/audio_generator.py --clear-cache --max-turns 5
```

**Generated Files Structure:**
```
tests/load/audio_cache/
├── insurance_inquiry_turn_1_of_5_abc123.pcm
├── insurance_inquiry_turn_2_of_5_def456.pcm
├── insurance_inquiry_turn_3_of_5_ghi789.pcm
├── insurance_inquiry_turn_4_of_5_jkl012.pcm
├── insurance_inquiry_turn_5_of_5_mno345.pcm
├── quick_question_turn_1_of_3_pqr678.pcm
├── quick_question_turn_2_of_3_stu901.pcm
└── quick_question_turn_3_of_3_vwx234.pcm
```

### 2. Run Detailed Statistics Load Tests

#### **Fixed Turn Count with Detailed Analysis**
```bash
# Run detailed 5-turn analysis (20 conversations, 5 concurrent)
python tests/load/detailed_statistics_analyzer.py \
  --turns 5 \
  --conversations 20 \
  --concurrent 5 \
  --url ws://localhost:8010/api/v1/media/stream
```

#### **Compare Different Turn Counts**
```bash
# Test 3-turn conversations
python tests/load/detailed_statistics_analyzer.py --turns 3 --conversations 15

# Test 5-turn conversations  
python tests/load/detailed_statistics_analyzer.py --turns 5 --conversations 20

# Test 7-turn conversations (extended insurance_inquiry)
python tests/load/detailed_statistics_analyzer.py --turns 7 --conversations 10
```

#### **Quick Validation Test**
```bash
# Fast test to validate setup
python tests/load/test_multi_turn.py
```

## 📊 Understanding Detailed Statistics

### **Comprehensive Per-Turn Analysis**
```
⏱️  OVERALL LATENCY STATISTICS

📈 Speech Recognition Latency Ms
  Count:      95
  Mean:     850.2ms
  P50:      820.1ms
  P95:     1150.3ms
  P99:     1380.7ms
  P99.9:   1520.4ms
  Min:      650.0ms
  Max:     1600.2ms
  StdDev:   180.5ms

🔄 PER-TURN POSITION ANALYSIS
Turn   Count    Success%  Recognition P95  Processing P95   E2E P95
-----------------------------------------------------------------------
1      20       100.0%    1050.2ms         1850.4ms         2100.1ms
2      20       95.0%     1120.8ms         1920.3ms         2250.7ms
3      19       95.0%     1180.5ms         2050.1ms         2400.2ms
4      18       90.0%     1250.3ms         2180.8ms         2580.5ms
5      17       85.0%     1320.7ms         2350.2ms         2750.3ms
```

### **Template Performance Comparison**
```
📋 TEMPLATE COMPARISON ANALYSIS

📝 Insurance Inquiry
  Conversations: 12
  Successful Turns: 57/60
  Avg Duration: 45.8s
  End-to-End: Mean=2150.3ms, P95=2580.1ms, P99=2850.7ms

📝 Quick Question  
  Conversations: 8
  Successful Turns: 23/24
  Avg Duration: 18.2s
  End-to-End: Mean=1850.2ms, P95=2100.5ms, P99=2350.1ms
```

### **Key Metrics Explained**

#### **Per-Turn Metrics**
- **Speech Recognition Latency**: Critical for responsiveness - target <1000ms
- **Agent Processing Latency**: LLM + TTS pipeline time - target <2000ms  
- **End-to-End Latency**: Total user experience - target <3000ms
- **Turn Success Rate**: Should stay >90% across all turn positions

#### **Performance Degradation Patterns**
- **Turn Position Impact**: Later turns often have higher latency
- **Template Complexity**: Longer conversations show accumulating delays
- **Concurrent Load Effect**: Higher concurrency increases P95/P99 latencies

## 🎭 Conversation Scenarios (Simplified)

### **Scenario 1: `insurance_inquiry` (5 turns)**
1. "Hello, my name is Alice Brown, my social is 1234, and my zip code is 60601"
2. "I'm calling about my auto insurance policy"  
3. "I need to understand what's covered under my current plan"
4. "What happens if I get into an accident?"
5. "Thank you for all the information, that's very helpful"

### **Scenario 2: `quick_question` (3 turns)**
1. "Hi there, I have a quick question"
2. "Can you help me check my account balance?"
3. "Thanks, that's all I needed to know"

## 🏗️ FAANG-Level Test Strategy

### **Development Testing**
```bash
# Quick validation (3 turns, 5 conversations)
python tests/load/detailed_statistics_analyzer.py --turns 3 --conversations 5 --concurrent 2
```

### **Performance Testing**
```bash
# Realistic load (5 turns, 20 conversations)  
python tests/load/detailed_statistics_analyzer.py --turns 5 --conversations 20 --concurrent 5
```

### **Stress Testing**
```bash
# Heavy load (5 turns, 50 conversations, 10 concurrent)
python tests/load/detailed_statistics_analyzer.py --turns 5 --conversations 50 --concurrent 10
```

### **Latency Profiling**
```bash
# Fixed turn count for consistent latency analysis
python tests/load/detailed_statistics_analyzer.py --turns 5 --conversations 30 --concurrent 3
```

## 📈 Performance Targets (FAANG Standards)

### **Latency Targets by Turn Position**
| Turn | Recognition P95 | Processing P95 | E2E P95 | Success Rate |
|------|----------------|----------------|---------|--------------|
| 1    | <1000ms        | <1800ms        | <2500ms | >98%         |
| 2    | <1100ms        | <1900ms        | <2600ms | >95%         |
| 3    | <1200ms        | <2000ms        | <2700ms | >92%         |
| 4    | <1300ms        | <2100ms        | <2800ms | >90%         |
| 5    | <1400ms        | <2200ms        | <2900ms | >88%         |

### **Conversation-Level Targets**
- **3-turn conversations**: <20s total duration, >95% success rate
- **5-turn conversations**: <50s total duration, >90% success rate
- **Concurrent capacity**: 10+ concurrent 5-turn conversations
- **Error rate**: <5% overall turn failure rate

## 🔧 Configuration Examples

### **Consistent Turn Analysis**
```python
config = LoadTestConfig(
    max_conversation_turns=5,
    min_conversation_turns=5,
    turn_variation_strategy="fixed",  # Same turns every time
    conversation_templates=["insurance_inquiry", "quick_question"]
)
```

### **Production Validation**
```python
config = LoadTestConfig(
    max_concurrent_conversations=10,
    total_conversations=50,
    max_conversation_turns=5,
    turn_variation_strategy="fixed"
)
```

## 💾 Output Files

### **Detailed Analysis JSON**
```
tests/load/results/detailed_stats_5turns_20250829_143022.json
```

Contains:
- Complete per-turn statistics with all percentiles
- Turn position analysis (performance by turn number)
- Template comparison metrics
- Failure analysis with error categorization
- Conversation-level statistics

### **Load Test Results JSON**  
```
tests/load/results/conversation_load_test_20250829_143022.json
```

Contains:
- Raw conversation metrics
- Configuration used
- Individual conversation details
- Error logs and timestamps

## 🚀 Quick Start Commands

```bash
# 1. Generate audio files (run once)
python tests/load/audio_generator.py --max-turns 5

# 2. Validate setup  
python tests/load/test_multi_turn.py

# 3. Run detailed analysis (5 turns, 20 conversations)
python tests/load/detailed_statistics_analyzer.py --turns 5 --conversations 20

# 4. Compare different turn counts
python tests/load/detailed_statistics_analyzer.py --turns 3 --conversations 15
python tests/load/detailed_statistics_analyzer.py --turns 5 --conversations 20
```

This framework now provides **production-grade detailed statistics** with **FAANG-level analysis depth** for your multi-turn conversation load testing! 🎯
