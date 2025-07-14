import React from 'react';
import ReactFlow, { ReactFlowProvider, MiniMap, Controls } from 'reactflow';
import 'reactflow/dist/style.css';

export default function MindMap({ nodes, edges }) {
  return (
    <ReactFlowProvider>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        panOnScroll
        zoomOnScroll
        defaultEdgeOptions={{
          markerEnd: { type: 'arrowclosed', width: 12, height: 12 }
        }}
        style={{ width: '100%', height: '100%', background: 'transparent' }}
      >
        <MiniMap
          nodeColor={n =>
            n.id === 'user-root'      ? '#0F766E' :
            n.id === 'assistant-root' ? '#4338CA' :
            n.style?.background       || '#334155'
          }
        />
        <Controls />
      </ReactFlow>
    </ReactFlowProvider>
  );
}
