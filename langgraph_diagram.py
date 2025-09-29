#!/usr/bin/env python3
"""
LangGraph Diagram Generator for TazaTicket Flight Search Chatbot
Generates a visual representation of the conversation flow and architecture
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, ConnectionPatch, Rectangle
import numpy as np

def create_langgraph_diagram():
    """Create a comprehensive LangGraph diagram for TazaTicket"""
    
    # Create figure with subplots for different views
    fig = plt.figure(figsize=(20, 16))
    
    # Main graph structure
    ax1 = plt.subplot2grid((3, 2), (0, 0), colspan=2, rowspan=2)
    ax1.set_title("TazaTicket LangGraph Architecture", fontsize=16, fontweight='bold', pad=20)
    
    # State machine detail
    ax2 = plt.subplot2grid((3, 2), (2, 0))
    ax2.set_title("Conversation State Machine", fontsize=12, fontweight='bold')
    
    # Tool flow detail
    ax3 = plt.subplot2grid((3, 2), (2, 1))
    ax3.set_title("Flight Search Tools", fontsize=12, fontweight='bold')
    
    # Main Graph Flow (ax1)
    # Define positions for nodes
    positions = {
        'START': (1, 8),
        'chatbot': (3, 8),
        'route_tools': (5, 8),
        'tools': (7, 8),
        'END': (9, 8),
        'memory_manager': (3, 6),
        'speech_processor': (1, 6),
        'translation_service': (5, 6),
        's3_handler': (7, 6),
        'flight_search_sm': (7, 4),
        'bulk_flight_search': (9, 4),
        'travelport_search': (8, 2),
        'dynamodb': (3, 4),
        'twilio_webhook': (1, 10)
    }
    
    # Color scheme
    colors = {
        'core_nodes': '#4A90E2',      # Blue for core LangGraph nodes
        'tools': '#7ED321',           # Green for tools
        'services': '#F5A623',        # Orange for services
        'storage': '#BD10E0',         # Purple for storage
        'external': '#B8E986',        # Light green for external
        'flow': '#50E3C2'            # Teal for flow control
    }
    
    # Draw main nodes
    node_styles = {
        'START': {'color': colors['flow'], 'shape': 'circle'},
        'chatbot': {'color': colors['core_nodes'], 'shape': 'box'},
        'route_tools': {'color': colors['flow'], 'shape': 'diamond'},
        'tools': {'color': colors['core_nodes'], 'shape': 'box'},
        'END': {'color': colors['flow'], 'shape': 'circle'},
        'memory_manager': {'color': colors['services'], 'shape': 'box'},
        'speech_processor': {'color': colors['services'], 'shape': 'box'},
        'translation_service': {'color': colors['services'], 'shape': 'box'},
        's3_handler': {'color': colors['services'], 'shape': 'box'},
        'flight_search_sm': {'color': colors['tools'], 'shape': 'box'},
        'bulk_flight_search': {'color': colors['tools'], 'shape': 'box'},
        'travelport_search': {'color': colors['external'], 'shape': 'box'},
        'dynamodb': {'color': colors['storage'], 'shape': 'cylinder'},
        'twilio_webhook': {'color': colors['external'], 'shape': 'box'}
    }
    
    # Draw nodes
    for node, (x, y) in positions.items():
        style = node_styles[node]
        
        if style['shape'] == 'circle':
            circle = plt.Circle((x, y), 0.3, color=style['color'], alpha=0.7)
            ax1.add_patch(circle)
        elif style['shape'] == 'diamond':
            # Diamond shape for decision nodes
            diamond = mpatches.RegularPolygon((x, y), 4, radius=0.4, 
                                            orientation=np.pi/4, 
                                            color=style['color'], alpha=0.7)
            ax1.add_patch(diamond)
        elif style['shape'] == 'cylinder':
            # Cylinder for database
            rect = Rectangle((x-0.4, y-0.2), 0.8, 0.4, 
                           color=style['color'], alpha=0.7)
            ax1.add_patch(rect)
        else:
            # Rectangle for regular nodes
            rect = FancyBboxPatch((x-0.5, y-0.25), 1.0, 0.5,
                                boxstyle="round,pad=0.05",
                                facecolor=style['color'], 
                                alpha=0.7,
                                edgecolor='black',
                                linewidth=1)
            ax1.add_patch(rect)
        
        # Add labels
        ax1.text(x, y, node.replace('_', '\n'), ha='center', va='center', 
                fontsize=8, fontweight='bold', wrap=True)
    
    # Draw edges with arrows
    edges = [
        ('START', 'chatbot', 'solid'),
        ('chatbot', 'route_tools', 'solid'),
        ('route_tools', 'tools', 'solid'),
        ('route_tools', 'END', 'solid'),
        ('tools', 'chatbot', 'solid'),
        ('twilio_webhook', 'chatbot', 'dashed'),
        ('chatbot', 'memory_manager', 'dashed'),
        ('memory_manager', 'dynamodb', 'solid'),
        ('speech_processor', 'chatbot', 'dashed'),
        ('speech_processor', 's3_handler', 'dashed'),
        ('chatbot', 'translation_service', 'dashed'),
        ('tools', 'flight_search_sm', 'solid'),
        ('tools', 'bulk_flight_search', 'solid'),
        ('flight_search_sm', 'travelport_search', 'solid'),
        ('bulk_flight_search', 'travelport_search', 'solid')
    ]
    
    for start, end, style in edges:
        x1, y1 = positions[start]
        x2, y2 = positions[end]
        
        linestyle = '--' if style == 'dashed' else '-'
        alpha = 0.6 if style == 'dashed' else 0.8
        
        ax1.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle='->', lw=1.5, 
                                  color='black', alpha=alpha,
                                  linestyle=linestyle))
    
    # Add flow annotations
    ax1.text(2, 9, 'User Input\n(Text/Voice)', ha='center', va='center', 
            bbox=dict(boxstyle="round,pad=0.3", facecolor='lightblue', alpha=0.5))
    
    ax1.text(6, 9, 'Tool\nSelection', ha='center', va='center',
            bbox=dict(boxstyle="round,pad=0.3", facecolor='lightgreen', alpha=0.5))
    
    ax1.text(8, 9, 'Response\nGeneration', ha='center', va='center',
            bbox=dict(boxstyle="round,pad=0.3", facecolor='lightyellow', alpha=0.5))
    
    # Set axis properties
    ax1.set_xlim(0, 10)
    ax1.set_ylim(1, 11)
    ax1.set_aspect('equal')
    ax1.axis('off')
    
    # State Machine Detail (ax2)
    sm_states = ['incomplete', 'complete']
    sm_positions = [(1, 2), (3, 2)]
    
    for i, (state, pos) in enumerate(zip(sm_states, sm_positions)):
        color = colors['tools'] if state == 'complete' else colors['services']
        rect = FancyBboxPatch((pos[0]-0.4, pos[1]-0.3), 0.8, 0.6,
                            boxstyle="round,pad=0.05",
                            facecolor=color, alpha=0.7)
        ax2.add_patch(rect)
        ax2.text(pos[0], pos[1], state, ha='center', va='center', fontweight='bold')
    
    # State transition arrow
    ax2.annotate('', xy=(2.6, 2), xytext=(1.4, 2),
                arrowprops=dict(arrowstyle='->', lw=2, color='black'))
    ax2.text(2, 2.5, 'All fields\ncomplete', ha='center', va='center', fontsize=8)
    
    # Required fields
    fields = ['origin', 'destination', 'departure_date', 'passengers', 'trip_type']
    for i, field in enumerate(fields):
        ax2.text(0.2, 1.5 - i*0.2, f'• {field}', fontsize=8, va='center')
    
    ax2.set_xlim(0, 4)
    ax2.set_ylim(0, 3)
    ax2.axis('off')
    
    # Tool Flow Detail (ax3)
    tool_flow = [
        ('User Query', (1, 2.5)),
        ('Parse Intent', (2, 2.5)),
        ('State Check', (3, 2.5)),
        ('Search/Wait', (4, 2.5)),
        ('Format Result', (5, 2.5))
    ]
    
    for i, (step, pos) in enumerate(tool_flow):
        color = colors['tools'] if i % 2 == 0 else colors['services']
        rect = FancyBboxPatch((pos[0]-0.3, pos[1]-0.2), 0.6, 0.4,
                            boxstyle="round,pad=0.02",
                            facecolor=color, alpha=0.7)
        ax3.add_patch(rect)
        ax3.text(pos[0], pos[1], step, ha='center', va='center', fontsize=7, fontweight='bold')
        
        if i < len(tool_flow) - 1:
            next_pos = tool_flow[i+1][1]
            ax3.annotate('', xy=(next_pos[0]-0.3, next_pos[1]), 
                        xytext=(pos[0]+0.3, pos[1]),
                        arrowprops=dict(arrowstyle='->', lw=1, color='black'))
    
    # Tool types
    ax3.text(3, 1.8, 'FlightSearchStateMachine', ha='center', va='center', 
            fontsize=8, bbox=dict(boxstyle="round", facecolor='lightgreen', alpha=0.5))
    ax3.text(3, 1.5, 'BulkFlightSearch', ha='center', va='center', 
            fontsize=8, bbox=dict(boxstyle="round", facecolor='lightblue', alpha=0.5))
    
    ax3.set_xlim(0, 6)
    ax3.set_ylim(1, 3)
    ax3.axis('off')
    
    # Add legend
    legend_elements = [
        mpatches.Patch(color=colors['core_nodes'], label='Core LangGraph Nodes'),
        mpatches.Patch(color=colors['tools'], label='Flight Search Tools'),
        mpatches.Patch(color=colors['services'], label='Support Services'),
        mpatches.Patch(color=colors['storage'], label='Data Storage'),
        mpatches.Patch(color=colors['external'], label='External APIs'),
        mpatches.Patch(color=colors['flow'], label='Flow Control')
    ]
    
    fig.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(0.98, 0.98))
    
    plt.tight_layout()
    return fig

def create_data_flow_diagram():
    """Create a detailed data flow diagram"""
    
    fig, ax = plt.subplots(figsize=(16, 12))
    ax.set_title("TazaTicket Data Flow Architecture", fontsize=16, fontweight='bold', pad=20)
    
    # Define layers
    layers = {
        'Input Layer': {
            'y': 10,
            'components': ['WhatsApp', 'Voice Message', 'Text Message'],
            'color': '#E3F2FD'
        },
        'Processing Layer': {
            'y': 8,
            'components': ['Speech-to-Text', 'Language Detection', 'Translation'],
            'color': '#F3E5F5'
        },
        'LangGraph Layer': {
            'y': 6,
            'components': ['Chatbot Node', 'Route Tools', 'Tool Execution'],
            'color': '#E8F5E8'
        },
        'Business Logic': {
            'y': 4,
            'components': ['State Machine', 'Flight Search', 'Bulk Search'],
            'color': '#FFF3E0'
        },
        'External APIs': {
            'y': 2,
            'components': ['Travelport', 'AssemblyAI', 'SpeechGen'],
            'color': '#FFEBEE'
        },
        'Storage Layer': {
            'y': 0,
            'components': ['DynamoDB', 'S3 Bucket', 'Memory Cache'],
            'color': '#F1F8E9'
        }
    }
    
    # Draw layers
    for layer_name, layer_info in layers.items():
        y = layer_info['y']
        components = layer_info['components']
        color = layer_info['color']
        
        # Draw layer background
        rect = Rectangle((0, y-0.8), 14, 1.6, facecolor=color, alpha=0.3, edgecolor='gray')
        ax.add_patch(rect)
        
        # Layer label
        ax.text(-0.5, y, layer_name, rotation=90, ha='center', va='center', 
               fontweight='bold', fontsize=10)
        
        # Draw components
        x_positions = np.linspace(2, 12, len(components))
        for i, (component, x) in enumerate(zip(components, x_positions)):
            rect = FancyBboxPatch((x-0.8, y-0.3), 1.6, 0.6,
                                boxstyle="round,pad=0.05",
                                facecolor='white', 
                                edgecolor='black',
                                linewidth=1)
            ax.add_patch(rect)
            ax.text(x, y, component, ha='center', va='center', fontsize=8, fontweight='bold')
    
    # Draw data flow arrows
    flow_connections = [
        # Input to Processing
        ((4, 9.2), (4, 8.8)),
        ((7, 9.2), (7, 8.8)),
        ((10, 9.2), (10, 8.8)),
        
        # Processing to LangGraph
        ((4, 7.2), (4, 6.8)),
        ((7, 7.2), (7, 6.8)),
        ((10, 7.2), (10, 6.8)),
        
        # LangGraph to Business Logic
        ((4, 5.2), (4, 4.8)),
        ((7, 5.2), (7, 4.8)),
        ((10, 5.2), (10, 4.8)),
        
        # Business Logic to External APIs
        ((7, 3.2), (7, 2.8)),
        
        # To Storage
        ((4, 3.2), (4, 0.8)),
        ((7, 1.2), (7, 0.8)),
        ((10, 3.2), (10, 0.8))
    ]
    
    for start, end in flow_connections:
        ax.annotate('', xy=end, xytext=start,
                   arrowprops=dict(arrowstyle='->', lw=1.5, color='blue', alpha=0.7))
    
    # Add data flow labels
    ax.text(1, 9, 'User Input', rotation=45, ha='center', va='center', 
           bbox=dict(boxstyle="round", facecolor='lightblue', alpha=0.7))
    
    ax.text(13, 5, 'AI Processing', rotation=-45, ha='center', va='center',
           bbox=dict(boxstyle="round", facecolor='lightgreen', alpha=0.7))
    
    ax.text(1, 1, 'Data Persistence', rotation=45, ha='center', va='center',
           bbox=dict(boxstyle="round", facecolor='lightcoral', alpha=0.7))
    
    ax.set_xlim(-1, 15)
    ax.set_ylim(-1, 11)
    ax.axis('off')
    
    return fig

if __name__ == "__main__":
    # Generate main LangGraph diagram
    print("Generating LangGraph Architecture Diagram...")
    fig1 = create_langgraph_diagram()
    fig1.savefig('tazaticket_langgraph_architecture.png', dpi=300, bbox_inches='tight')
    print("✅ Saved: tazaticket_langgraph_architecture.png")
    
    # Generate data flow diagram
    print("Generating Data Flow Diagram...")
    fig2 = create_data_flow_diagram()
    fig2.savefig('tazaticket_data_flow.png', dpi=300, bbox_inches='tight')
    print("✅ Saved: tazaticket_data_flow.png")
    
    # Show diagrams
    plt.show()
    
    print("\n" + "="*60)
    print("TAZATICKET LANGGRAPH ARCHITECTURE SUMMARY")
    print("="*60)
    
    print("\n🏗️  CORE COMPONENTS:")
    print("├── LangGraph State Management")
    print("│   ├── Chatbot Node (GPT-4o-mini)")
    print("│   ├── Tool Router (Conditional Logic)")
    print("│   └── Tool Execution Node")
    print("│")
    print("├── Flight Search Tools")
    print("│   ├── FlightSearchStateMachine")
    print("│   └── BulkFlightSearch")
    print("│")
    print("└── Support Services")
    print("    ├── Memory Manager (DynamoDB)")
    print("    ├── Speech Processor (AssemblyAI + SpeechGen)")
    print("    ├── Translation Service")
    print("    └── S3 Handler")
    
    print("\n🔄 CONVERSATION FLOW:")
    print("1. User Input → Twilio Webhook")
    print("2. Voice/Text Processing → Language Detection")
    print("3. Translation to English (if needed)")
    print("4. LangGraph Processing:")
    print("   ├── Chatbot Node (LLM)")
    print("   ├── Route Tools (Decision)")
    print("   └── Tool Execution")
    print("5. Flight Search via Travelport")
    print("6. Response Translation")
    print("7. Voice/Text Response via Twilio")
    
    print("\n📊 STATE MACHINE:")
    print("Required Fields: origin, destination, departure_date, passengers, trip_type")
    print("States: incomplete → complete")
    print("Triggers: FlightSearchStateMachine or BulkFlightSearch")
    
    print("\n💾 MEMORY MANAGEMENT:")
    print("├── Context Window: 15 pairs")
    print("├── Batch Buffer: Auto-flush")
    print("├── Session Timeout: Configurable")
    print("└── DynamoDB Persistence")
    
    print("\n🌐 MULTI-LANGUAGE SUPPORT:")
    print("├── 60+ Languages via Google Translate")
    print("├── Voice Recognition (AssemblyAI)")
    print("├── Voice Synthesis (SpeechGen)")
    print("└── Special Punjabi Handling")
    
    print("\n" + "="*60)

