class ConversationFlowSM:
    def __init__(self):
        
        """
        This is a state machine that will determine the comversation flow for the user.
        It checks whether all required information is complete and if there is missing information it will directly 
        ask the user for the missing information in the required language and mode of choice. 

        It has two states: "Complete" and "Incomplete".
        Only one transition: The state changes to "incomplete" if any of the variables are missing.

        Here are the list of methods available:
        1) set_variable(var_name, var_value) - > allows you to change a variable in the state machine
        2) unset_variable(var_name) - > allows you to unset a variable in the state machine
        """
        self.current_state = "incomplete"
        
        self.detcted_language = None
        self.origin = None
        self.destination = None
        self.departure_date = None
        self.number_of_passengers = None
        self.type_of_trip = None
        self.return_date = None

        def set_variable(self, var_name, var_value):
            if hasattr(self, var_name):
                setattr(self, var_name, var_value)
                print(f"Set Variable: {var_name} to {var_value}")
                self._update_state()
            else:
                print(f"Variable {var_name} not found")

        def unset_variable(self, var_name):
            if hasattr(self, var_name):
                setattr(self, var_name, None)
                print(f"Unset Variable: {var_name}")
                self._update_state()
            else:
                print(f"Variable {var_name} not found")

        def _is_complete(self):

            required_vars = [
                self.detcted_language,
                self.origin,
                self.destination,
                self.departure_date,
                self.number_of_passengers,
                self.type_of_trip
            ]

            if any(var is None for var in required_vars):
                return False

            if self.type_of_trip == "round-trip" and self.return_date is None:
                return False
            
            return True

        def _update_state(self):
            old_state = self.current_state

            if self._is_complete():
                self.current_state = "complete"
            else:
                self.current_state = "incomplete"
            if old_state != self.current_state:
                print(f"State changed from {old_state} to {self.current_state}")
                print(f"Variable values: {self.__dict__}")

        def get_state(self):
            return self.current_state

        def get_missing_variables(self):
            missing = []
            vars = [
                self.detcted_language,
                self.origin,
                self.destination,
                self.departure_date,
                self.number_of_passengers,
                self.type_of_trip
            ]

            for var_name, value in vars.items():
                if value is None:
                    missing.append(var_name)

            if self.type_of_trip == "round trip" and self.return_date is None:
                missing.append(self.return_date)
        
        def status(self):
            """Print current status"""
            print(f"\n--- Travel Booking Status ---")
            print(f"State: {self.current_state}")
            print(f"detected_language: {self.detected_language}")
            print(f"origin: {self.origin}")
            print(f"destination: {self.destination}")
            print(f"departure_date: {self.departure_date}")
            print(f"number_of_passengers: {self.number_of_passengers}")
            print(f"type_of_trip: {self.type_of_trip}")
            print(f"return_date: {self.return_date}")
            
            missing = self.get_missing_variables()
            if missing:
                print(f"Missing variables: {missing}")
            else:
                print("All required variables are set!")
            print("-" * 30)
